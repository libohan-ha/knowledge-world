export function clearWorldDisplayState() {
  try {for(const key of Object.keys(localStorage)) if(key==='kw-world-seen'||key.startsWith('kw-world-device:')||key.startsWith('kw-world-seen:'))localStorage.removeItem(key)} catch {/* Private/limited storage must not block login or recovery. */}
}
