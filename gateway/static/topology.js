// AIOps NOC Platform - Vis.js Network Topology Renderer with SVG Nodes

let network = null;
let nodesDataSet = null;
let edgesDataSet = null;
let originalNodesMap = {}; // Tracks original styling to easily revert alarm states

// High-fidelity glowing SVG assets as Data URIs
const routerSvg = `data:image/svg+xml;utf8,` + encodeURIComponent(`
<svg xmlns="http://www.w3.org/2000/svg" width="60" height="60" viewBox="0 0 60 60">
  <defs>
    <linearGradient id="bgGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#111827"/>
      <stop offset="100%" stop-color="#030712"/>
    </linearGradient>
    <linearGradient id="glowRouter" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#60a5fa"/>
      <stop offset="100%" stop-color="#3b82f6"/>
    </linearGradient>
  </defs>
  <circle cx="30" cy="30" r="26" fill="url(#bgGrad)" stroke="url(#glowRouter)" stroke-width="2.5"/>
  <circle cx="30" cy="30" r="26" fill="none" stroke="#60a5fa" stroke-width="1" opacity="0.4" filter="blur(2px)"/>
  <path d="M22 30h16M30 22v16M24 24l12 12M36 24L24 36" stroke="#60a5fa" stroke-width="2" stroke-linecap="round"/>
  <circle cx="30" cy="30" r="4" fill="#0f172a" stroke="#60a5fa" stroke-width="2"/>
</svg>
`);

const switchSvg = `data:image/svg+xml;utf8,` + encodeURIComponent(`
<svg xmlns="http://www.w3.org/2000/svg" width="60" height="60" viewBox="0 0 60 60">
  <defs>
    <linearGradient id="bgGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#111827"/>
      <stop offset="100%" stop-color="#030712"/>
    </linearGradient>
    <linearGradient id="glowSwitch" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#c084fc"/>
      <stop offset="100%" stop-color="#a855f7"/>
    </linearGradient>
  </defs>
  <circle cx="30" cy="30" r="26" fill="url(#bgGrad)" stroke="url(#glowSwitch)" stroke-width="2.5"/>
  <circle cx="30" cy="30" r="26" fill="none" stroke="#c084fc" stroke-width="1" opacity="0.4" filter="blur(2px)"/>
  <rect x="20" y="24" width="20" height="12" rx="1.5" fill="none" stroke="#c084fc" stroke-width="2"/>
  <rect x="23" y="28" width="4" height="4" rx="0.5" fill="#c084fc"/>
  <rect x="33" y="28" width="4" height="4" rx="0.5" fill="#c084fc"/>
</svg>
`);

const serverSvg = `data:image/svg+xml;utf8,` + encodeURIComponent(`
<svg xmlns="http://www.w3.org/2000/svg" width="60" height="60" viewBox="0 0 60 60">
  <defs>
    <linearGradient id="bgGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#111827"/>
      <stop offset="100%" stop-color="#030712"/>
    </linearGradient>
    <linearGradient id="glowServer" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#34d399"/>
      <stop offset="100%" stop-color="#10b981"/>
    </linearGradient>
  </defs>
  <circle cx="30" cy="30" r="26" fill="url(#bgGrad)" stroke="url(#glowServer)" stroke-width="2.5"/>
  <circle cx="30" cy="30" r="26" fill="none" stroke="#34d399" stroke-width="1" opacity="0.4" filter="blur(2px)"/>
  <rect x="20" y="21" width="20" height="5" rx="0.5" fill="none" stroke="#34d399" stroke-width="1.5"/>
  <rect x="20" y="28" width="20" height="5" rx="0.5" fill="none" stroke="#34d399" stroke-width="1.5"/>
  <rect x="20" y="35" width="20" height="5" rx="0.5" fill="none" stroke="#34d399" stroke-width="1.5"/>
  <circle cx="23" cy="23.5" r="0.75" fill="#34d399"/>
  <circle cx="23" cy="30.5" r="0.75" fill="#34d399"/>
  <circle cx="23" cy="37.5" r="0.75" fill="#34d399"/>
</svg>
`);

const alarmSvg = `data:image/svg+xml;utf8,` + encodeURIComponent(`
<svg xmlns="http://www.w3.org/2000/svg" width="60" height="60" viewBox="0 0 60 60">
  <defs>
    <linearGradient id="bgAlert" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#7f1d1d"/>
      <stop offset="100%" stop-color="#180404"/>
    </linearGradient>
    <linearGradient id="glowAlert" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#f87171"/>
      <stop offset="100%" stop-color="#ef4444"/>
    </linearGradient>
  </defs>
  <circle cx="30" cy="30" r="26" fill="url(#bgAlert)" stroke="url(#glowAlert)" stroke-width="2.5"/>
  <circle cx="30" cy="30" r="26" fill="none" stroke="#f87171" stroke-width="1.5" opacity="0.5" filter="blur(2px)"/>
  <path d="M30 18l11 19H19z" fill="none" stroke="#f87171" stroke-width="2" stroke-linejoin="round"/>
  <line x1="30" y1="25" x2="30" y2="30" stroke="#f87171" stroke-width="2" stroke-linecap="round"/>
  <circle cx="30" cy="34" r="1" fill="#f87171"/>
</svg>
`);

function initTopology(devices) {
    const container = document.getElementById('topology-graph');
    
    const nodesArray = [];
    const edgesArray = [];
    
    devices.forEach(dev => {
        let nodeImage = switchSvg; // default
        let level = 2;
        
        const isRouter = dev.hostname.includes('router') || 
                         (dev.sysName && dev.sysName.toLowerCase().includes('router')) ||
                         (dev.os && (dev.os.toLowerCase().includes('router') || dev.os.toLowerCase().includes('ios') || dev.os.toLowerCase().includes('routeros'))) ||
                         dev.ip.startsWith('10.');
                         
        const isServer = dev.hostname.includes('server') || dev.hostname.includes('san') || dev.hostname.includes('storage') ||
                         (dev.os && dev.os.toLowerCase().includes('linux')) ||
                         (dev.hardware && dev.hardware.toLowerCase().includes('ubuntu'));
        
        if (isRouter) {
            nodeImage = routerSvg;
            level = 1;
        } else if (isServer) {
            nodeImage = serverSvg;
            level = 3;
        }
        
        let cleanLabel = dev.sysName ? dev.sysName : dev.hostname.split('.')[0];
        
        const nodeObj = {
            id: dev.device_id || dev.id,
            label: cleanLabel,
            title: `Host: ${dev.hostname}\nIP: ${dev.ip}\nModel: ${dev.hardware || 'Unknown'}\nOS: ${dev.os || 'Unknown'}`,
            shape: 'image',
            image: nodeImage,
            size: level === 1 ? 36 : (level === 2 ? 30 : 26),
            font: { color: '#f8fafc', face: 'Outfit', size: 12, strokeWidth: 0 },
            level: level,
            deviceData: dev,
            shadow: {
                enabled: true,
                color: 'rgba(0, 0, 0, 0.45)',
                size: 8,
                x: 4,
                y: 4
            }
        };
        
        nodesArray.push(nodeObj);
        originalNodesMap[dev.hostname] = { image: nodeImage, size: nodeObj.size };
    });
    
    if (devices.length > 1) {
        const routers = nodesArray.filter(n => n.level === 1);
        const coreNodeId = routers.length > 0 ? routers[0].id : (devices[0].device_id || devices[0].id);
        
        for (let i = 0; i < devices.length; i++) {
            const dev = devices[i];
            if ((dev.device_id || dev.id) === coreNodeId) continue;
            
            edgesArray.push({
                from: dev.device_id || dev.id,
                to: coreNodeId,
                width: dev.hostname.includes('server') ? 1.5 : 2.5,
                color: { color: 'rgba(147, 51, 234, 0.25)', highlight: '#a855f7' }
            });
        }
    }

    nodesDataSet = new vis.DataSet(nodesArray);
    edgesDataSet = new vis.DataSet(edgesArray);
    
    const data = {
        nodes: nodesDataSet,
        edges: edgesDataSet
    };
    
    const options = {
        layout: {
            hierarchical: {
                direction: 'UD',
                sortMethod: 'directed',
                nodeSpacing: 140,
                levelSeparation: 120,
                shakeTowards: 'leaves'
            }
        },
        nodes: {
            scaling: { min: 15, max: 40 }
        },
        edges: {
            smooth: {
                type: 'cubicBezier',
                forceDirection: 'vertical',
                roundness: 0.5
            }
        },
        interaction: {
            hover: true,
            tooltipDelay: 100,
            navigationButtons: false
        },
        physics: false
    };
    
    network = new vis.Network(container, data, options);
    
    network.on("click", (params) => {
        if (params.nodes.length > 0) {
            const nodeId = params.nodes[0];
            const node = nodesDataSet.get(nodeId);
            if (node && node.deviceData) {
                window.inspectDevice(node.deviceData);
            }
        }
    });

    if (devices.length > 0) {
        window.inspectDevice(devices[0]);
    }
}

function setTopologyNodeAlert(hostname) {
    if (!nodesDataSet) return;
    
    const matchedNode = nodesDataSet.get({
        filter: (item) => item.deviceData.hostname === hostname
    });
    
    if (matchedNode.length > 0) {
        const node = matchedNode[0];
        
        nodesDataSet.update({
            id: node.id,
            image: alarmSvg,
            size: node.size * 1.15
        });
        
        window.inspectDevice(node.deviceData);
    }
}

function resetTopologyAlerts() {
    if (!nodesDataSet) return;
    
    nodesDataSet.get().forEach(node => {
        const orig = originalNodesMap[node.deviceData.hostname];
        if (orig) {
            nodesDataSet.update({
                id: node.id,
                image: orig.image,
                size: orig.size
            });
        }
    });
}
