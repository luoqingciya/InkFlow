import type { InkFlowApi } from './index'

declare global {
  interface Window {
    inkflow: InkFlowApi
  }
}

export {}
