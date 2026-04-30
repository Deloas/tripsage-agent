/// <reference types="vite/client" />

// 这里集中声明 Vite 注入的前端环境变量，避免 import.meta.env 在严格模式下报错。
interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
