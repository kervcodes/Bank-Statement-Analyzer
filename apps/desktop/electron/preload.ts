import { contextBridge, ipcRenderer } from 'electron'
import type { PublicSettings, SettingsPatch } from './settings'

// The only privileged surface the renderer gets: the OS dark-mode flag/
// subscription, and settings get/save (which is how a plaintext API key
// reaches safeStorage -- it never touches Node/fs itself). No arbitrary IPC.
contextBridge.exposeInMainWorld('desktop', {
  shouldUseDarkColors: (): boolean => ipcRenderer.sendSync('theme:get'),
  onThemeChange: (cb: (dark: boolean) => void) => {
    const listener = (_e: unknown, dark: boolean) => cb(dark)
    ipcRenderer.on('theme:changed', listener)
    return () => ipcRenderer.removeListener('theme:changed', listener)
  },
  getSettings: (): Promise<PublicSettings> => ipcRenderer.invoke('settings:get'),
  saveSettings: (patch: SettingsPatch): Promise<PublicSettings> =>
    ipcRenderer.invoke('settings:save', patch),
})
