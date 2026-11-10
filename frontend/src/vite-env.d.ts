/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Адрес API журналов (по умолчанию /journals — тот же домен, что у платформы). */
  readonly VITE_API_BASE?: string
  /** Вход по паролю внутри журналов (стенд разработчика); в бою вход — через платформу. */
  readonly VITE_DEV_LOGIN?: string
}
