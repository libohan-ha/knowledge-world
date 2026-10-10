import {defineConfig} from 'vite'
import react from '@vitejs/plugin-react'
export default defineConfig({plugins:[react()],server:{port:Number(process.env.KW_DEV_WEB_PORT||5173),strictPort:true,proxy:{'/api':'http://127.0.0.1:'+(process.env.KW_DEV_API_PORT||8000)}},build:{assetsInlineLimit:0,chunkSizeWarningLimit:700,reportCompressedSize:false,rolldownOptions:{output:{codeSplitting:{groups:[{name:'three-engine',test:/node_modules[\\/]three[\\/]/,priority:20},{name:'three-react',test:/node_modules[\\/](@react-three|react-reconciler)[\\/]/,priority:10}]}}}}})
