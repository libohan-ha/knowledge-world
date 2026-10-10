import {createContext,useContext} from 'react'
import type {Wallet,Schema} from './shared/api/client'
export const AppContext=createContext<{profile:Schema<'ProfileView'> & {display_epoch:string};wallet:Wallet;today:string;isTest:boolean;threadId:string|null;setThreadId:(id:string)=>void;agentOpen:boolean;setAgentOpen:(open:boolean)=>void}>(null!)
export const useApp=()=>useContext(AppContext)
