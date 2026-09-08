import { contextBridge, ipcRenderer } from 'electron'

// The only privileged surface the renderer gets: the OS dark-mode flag and a
// change subscription. No Node, no fs, no arbitrary IPC.
contextBridge.exposeInMainWorld('desktop', {
  shouldUseDarkColors: (): boolean => ipcRenderer.sendSync('theme:get'),
  onThemeChange: (cb: (dark: boolean) => void) => {
    const listener = (_e: unknown, dark: boolean) => cb(dark)
    ipcRenderer.on('theme:changed', listener)
    return () => ipcRenderer.removeListener('theme:changed', listener)
  },
})
