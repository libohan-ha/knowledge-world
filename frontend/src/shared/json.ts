/** Narrow extensible JSON fields from generated Pydantic contracts. */
export const record=(value:unknown):Record<string,unknown>=>value!==null&&typeof value==='object'&&!Array.isArray(value)?value as Record<string,unknown>:{}
export const number=(value:unknown,fallback=0)=>typeof value==='number'&&Number.isFinite(value)?value:fallback
export const string=(value:unknown,fallback='')=>typeof value==='string'?value:fallback
export const strings=(value:unknown)=>Array.isArray(value)?value.filter((item):item is string=>typeof item==='string'):[]
