import json
import httpx
from typing import Dict, Any
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from gateway.config import settings

# Define structured output representation for AIOps recommendations
class AIAnalysisResult(BaseModel):
    answer: str = Field(description="The natural language direct answer to the user's inquiry, using live network state context if applicable. Use formatted HTML tags (like <p>, <ul>, <li>, <strong>, <br>) for nice visual rendering. Be conversational, thorough, and highly technical.")
    possible_root_cause: str = Field(description="The primary suspected reason behind the alert or N/A if not applicable.")
    impact_assessment: str = Field(description="Evaluation of down-stream impact and severity or N/A if not applicable.")
    suggested_remediation_playbook: str = Field(description="Step-by-step mitigation or configuration commands to resolve the issue or N/A if not applicable.")
    confidence_score: float = Field(description="Confidence score between 0.0 and 1.0.")

def analyze_alert_with_gemini(alert_string: str, api_key: str, model_name: str = "gemini-2.5-flash") -> Dict[str, Any]:
    """
    Parses network alerts using the Gemini API with structured JSON output configurations.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    
    prompt = (
        "You are a Senior Network Automation Expert and Lead AI Ops Engineer.\n"
        "Analyze the user's inquiry alongside the provided live network state context (list of active devices, status, and alerts from LibreNMS).\n"
        "Use this live context to directly answer their questions, deduce the root cause (or state if all is healthy), evaluate downstream impact, and provide a suggested Ansible/NAPALM remediation playbook.\n"
        "Respond ONLY in the JSON schema defined in the responseSchema configuration.\n"
        f"Alert Data:\n{alert_string}"
    )
    
    payload = {
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "answer": { "type": "STRING", "description": "The natural language direct answer to the user's inquiry, using live network state context if applicable. Use formatted HTML tags (like <p>, <ul>, <li>, <strong>, <br>) for nice visual rendering." },
                    "possible_root_cause": { "type": "STRING", "description": "The primary suspected reason behind the alert or N/A if not applicable." },
                    "impact_assessment": { "type": "STRING", "description": "Evaluation of down-stream impact and severity or N/A if not applicable." },
                    "suggested_remediation_playbook": { "type": "STRING", "description": "Step-by-step mitigation or configuration commands to resolve the issue or N/A if not applicable." },
                    "confidence_score": { "type": "NUMBER", "description": "Confidence score between 0.0 and 1.0." }
                },
                "required": ["answer", "possible_root_cause", "impact_assessment", "suggested_remediation_playbook", "confidence_score"]
            }
        }
    }
    
    try:
        with httpx.Client() as client:
            response = client.post(url, headers=headers, json=payload, timeout=20.0)
            response.raise_for_status()
            res_data = response.json()
            
            content_text = res_data['candidates'][0]['content']['parts'][0]['text']
            return json.loads(content_text)
    except Exception as e:
        return {
            "possible_root_cause": f"Gemini API invocation error: {str(e)}",
            "impact_assessment": "Failed to query Gemini backend",
            "suggested_remediation_playbook": "Check network connectivity manually. Inspect logs on device.",
            "confidence_score": 0.0
        }

PLAYBOOK_DATABASE = [
    {
        "title": "Verify BGP Neighbor Status Playbook",
        "text": (
            "Remediation Playbook: BGP Session Down Recovery\n"
            "Steps:\n"
            "1. Run CLI command: show ip bgp summary\n"
            "2. Identify if neighbor status is Active or Idle.\n"
            "3. Ping BGP peer interface to verify routing path.\n"
            "4. Check ACLs and firewall rules restricting TCP port 179.\n"
            "5. Execute reset ip bgp * soft in if needed."
        )
    },
    {
        "title": "Interface Port Shutdown & Recovery Playbook",
        "text": (
            "Remediation Playbook: Physical Interface Failure\n"
            "Steps:\n"
            "1. Run CLI command: show interface <interface-name> status\n"
            "2. Verify status (down/down, admin down, or err-disabled).\n"
            "3. If admin down, run configure terminal -> interface <interface> -> no shutdown.\n"
            "4. Check optic transceiver health: show interfaces <interface> transceiver.\n"
            "5. Inspect physical patching/cabling if link flap persists."
        )
    },
    {
        "title": "OSPF Routing Path Convergence Playbook",
        "text": (
            "Remediation Playbook: OSPF Neighbor Adjacency Lost\n"
            "Steps:\n"
            "1. Run CLI command: show ip ospf neighbor\n"
            "2. Verify neighborhood state (Init, 2-Way, Exstart, Full).\n"
            "3. Check MTU mismatches on peer interfaces: show ip interface.\n"
            "4. Verify OSPF hello and dead interval timers align.\n"
            "5. Clear ospf process to trigger convergence."
        )
    },
    {
        "title": "VLAN Tagging & Trunk Audit Playbook",
        "text": (
            "Remediation Playbook: VLAN Mismatch or Trunk Link Down\n"
            "Steps:\n"
            "1. Run CLI command: show interfaces trunk\n"
            "2. Verify allowed and active VLANs list.\n"
            "3. Confirm Native VLAN settings match on both trunk ports.\n"
            "4. Audit spanning-tree state for blockages: show spanning-tree vlan <id>.\n"
            "5. Update switchport trunk allowed vlan configs."
        )
    },
    {
        "title": "High CPU and Control Plane Polling Mitigation Playbook",
        "text": (
            "Remediation Playbook: High CPU / SNMP Polling Exhaustion\n"
            "Steps:\n"
            "1. Run CLI command: show processes cpu sorted\n"
            "2. Identify processes consuming high processor resources.\n"
            "3. Check if SNMP polling or syslog processes are over-subscribed.\n"
            "4. Apply SNMP rate-limiting: snmp-server community <string> limit <rate>.\n"
            "5. Configure control-plane policing (CoPP) to shield control plane."
        )
    }
]

def rerank_remediation_playbooks(alert_string: str, api_key: str) -> str:
    """
    Queries OpenRouter's /rerank endpoint using the nvidia/llama-nemotron-rerank-vl-1b-v2:free model
    to find the most relevant playbook template for the network alert.
    """
    if not api_key or api_key.startswith("mock") or "your_openai" in api_key:
        query_lower = alert_string.lower()
        if "bgp" in query_lower:
            return PLAYBOOK_DATABASE[0]["text"]
        elif "ospf" in query_lower:
            return PLAYBOOK_DATABASE[2]["text"]
        elif "vlan" in query_lower or "trunk" in query_lower:
            return PLAYBOOK_DATABASE[3]["text"]
        elif "cpu" in query_lower or "snmp" in query_lower:
            return PLAYBOOK_DATABASE[4]["text"]
        else:
            return PLAYBOOK_DATABASE[1]["text"]

    url = "https://openrouter.ai/api/v1/rerank"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    documents = [{"text": pb["text"]} for pb in PLAYBOOK_DATABASE]
    payload = {
        "model": "nvidia/llama-nemotron-rerank-vl-1b-v2:free",
        "query": alert_string,
        "documents": documents,
        "top_n": 1
    }
    
    try:
        with httpx.Client() as client:
            response = client.post(url, headers=headers, json=payload, timeout=20.0)
            response.raise_for_status()
            res_data = response.json()
            results = res_data.get("results", [])
            if results:
                top_idx = results[0]["index"]
                relevance = results[0]["relevance_score"]
                matched_pb = PLAYBOOK_DATABASE[top_idx]
                return f"[📌 Ranked Playbook: {matched_pb['title']} (OpenRouter Rerank Score: {relevance:.4f})]\n\n{matched_pb['text']}"
    except Exception as e:
        print(f"Rerank API error: {e}")
        
    query_lower = alert_string.lower()
    if "bgp" in query_lower:
        return f"[⚠️ Rerank Fallback (Local Match)]\n\n{PLAYBOOK_DATABASE[0]['text']}"
    elif "ospf" in query_lower:
        return f"[⚠️ Rerank Fallback (Local Match)]\n\n{PLAYBOOK_DATABASE[2]['text']}"
    elif "vlan" in query_lower or "trunk" in query_lower:
        return f"[⚠️ Rerank Fallback (Local Match)]\n\n{PLAYBOOK_DATABASE[3]['text']}"
    elif "cpu" in query_lower or "snmp" in query_lower:
        return f"[⚠️ Rerank Fallback (Local Match)]\n\n{PLAYBOOK_DATABASE[4]['text']}"
    else:
        return f"[⚠️ Rerank Fallback (Local Match)]\n\n{PLAYBOOK_DATABASE[1]['text']}"

def analyze_alert_with_llm(alert_string: str, api_key: str, model_name: str = "gpt-4o-mini", provider: str = "openai") -> Dict[str, Any]:
    """
    General entry point routing log requests to Gemini or OpenAI depending on configured LLM provider.
    """
    if not api_key or api_key.startswith("mock") or "your_openai" in api_key or "your_gemini" in api_key:
        matched_playbook = rerank_remediation_playbooks(alert_string, api_key)
        return {
            "answer": "Simulated response: A BGP session has been reported down. Based on mock context, there is a connection issue with neighbor 10.254.0.2.",
            "possible_root_cause": "Simulated RCA: The remote BGP peer closed the connection. This is likely caused by an interface flap or peer BGP daemon crash on neighbor 10.254.0.2.",
            "impact_assessment": "Downstream traffic routing via AS 65002 is interrupted. High risk of packet loss or suboptimal routing for multi-homed paths.",
            "suggested_remediation_playbook": (
                "- name: Verify BGP Neighbor Status\n"
                "  cisco.ios.ios_command:\n"
                "    commands:\n"
                "      - show ip bgp neighbors 10.254.0.2\n"
                "      - show ip interface brief | include 10.254\n"
                f"\n\n--------------------------------------------------\n"
                f"{matched_playbook}"
            ),
            "confidence_score": 0.95
        }

    if provider.lower() == "gemini":
        gemini_model = "gemini-2.5-flash" if "gemini" not in model_name else model_name
        return analyze_alert_with_gemini(alert_string, api_key, gemini_model)

    original_model = model_name
    fallback_active = "rerank" in model_name.lower()
    actual_model = "nvidia/nemotron-nano-9b-v2:free" if fallback_active else model_name

    try:
        parser = PydanticOutputParser(pydantic_object=AIAnalysisResult)
        
        system_instruction = (
            "You are a Senior Network Automation Expert and Lead AI Ops Engineer.\n"
            "Analyze the user's inquiry alongside the provided live network state context (list of active devices, status, and alerts from LibreNMS).\n"
            "Use this live context to directly answer their questions, deduce the root cause (or state if all is healthy), evaluate downstream impact, and provide a suggested Ansible/NAPALM remediation playbook.\n"
            "Respond ONLY in the JSON schema defined below.\n"
            "{format_instructions}"
        )
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_instruction),
            ("user", "Alert Data: {alert_data}")
        ])
        
        llm = ChatOpenAI(
            model=actual_model, 
            temperature=0.0, 
            openai_api_key=api_key,
            openai_api_base=settings.OPENAI_API_BASE
        )
        chain = prompt | llm | parser
        
        try:
            result: AIAnalysisResult = chain.invoke({
                "alert_data": alert_string,
                "format_instructions": parser.get_format_instructions()
            })
            res_dict = result.dict()
        except Exception as primary_exc:
            if not fallback_active:
                fallback_active = True
                actual_model = "nvidia/nemotron-nano-9b-v2:free"
                llm = ChatOpenAI(
                    model=actual_model,
                    temperature=0.0,
                    openai_api_key=api_key,
                    openai_api_base=settings.OPENAI_API_BASE
                )
                chain = prompt | llm | parser
                result = chain.invoke({
                    "alert_data": alert_string,
                    "format_instructions": parser.get_format_instructions()
                })
                res_dict = result.dict()
            else:
                raise primary_exc
        
        if fallback_active:
            res_dict["possible_root_cause"] = f"[⚠️ Fallback: {original_model} is a reranker model and not chat-compatible. Using {actual_model}]\n\n" + res_dict["possible_root_cause"]
            
        # Call OpenRouter /rerank endpoint using original_model (the rerank model)
        matched_playbook = rerank_remediation_playbooks(alert_string, api_key)
        res_dict["suggested_remediation_playbook"] = (
            f"{res_dict['suggested_remediation_playbook']}\n\n"
            f"--------------------------------------------------\n"
            f"{matched_playbook}"
        )

        return res_dict
        
    except Exception as e:
        return {
            "possible_root_cause": f"Failed to analyze alert due to exception: {str(e)}",
            "impact_assessment": "Unknown downstream impact",
            "suggested_remediation_playbook": "Check network connectivity manually. Inspect logs on device.",
            "confidence_score": 0.0
        }

# Example local test run execution block
if __name__ == "__main__":
    sample_alert = (
        "LibreNMS Alert:\n"
        "Device: core-sw-01.headquarters.net (192.168.10.1)\n"
        "Severity: Critical\n"
        "Rule: BGP Session Down\n"
        "Msg: BGP Session to peer 10.254.0.2 (AS 65002) is down. State: Active. Duration: 5m.\n"
        "Syslog: %BGP-5-ADJCHANGE: neighbor 10.254.0.2 Down - Peer closed BGP session"
    )
    
    print("Testing locally with mock API keys...")
    analysis = analyze_alert_with_llm(sample_alert, api_key="mock_key_for_testing")
    print(json.dumps(analysis, indent=2))
