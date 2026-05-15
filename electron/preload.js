const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('networkMonitor', {
  start:       (protocol) => ipcRenderer.send('network:start', protocol),
  stop:        ()         => ipcRenderer.send('network:stop'),
  subscribe:   (universe) => ipcRenderer.send('network:subscribe', universe),
  unsubscribe: ()         => ipcRenderer.send('network:unsubscribe'),

  onUniverses: (cb) => {
    const handler = (_, data) => cb(data);
    ipcRenderer.on('network:universes', handler);
    return () => ipcRenderer.removeListener('network:universes', handler);
  },
  onChannels: (cb) => {
    const handler = (_, data) => cb(data);
    ipcRenderer.on('network:channels', handler);
    return () => ipcRenderer.removeListener('network:channels', handler);
  },
});
