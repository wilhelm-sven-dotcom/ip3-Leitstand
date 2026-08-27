/** Einstiegspunkt der Oberfläche. */

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { SitzungProvider } from '@/sitzung/SitzungKontext'
import { AppRouten } from '@/router'

import '@/styles/fonts.css'
import '@/styles/tokens.css'
import '@/styles/basis.css'
import '@/komponenten/komponenten.css'

const abfragen = new QueryClient({
  defaultOptions: {
    queries: {
      // Kein automatisches Neuladen beim Fensterwechsel: die Daten des Leitstands ändern
      // sich in Minuten, nicht in Sekunden, und ein Neuladen mitten in einer Eingabe
      // irritiert mehr, als es hilft.
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 30 * 1000,
    },
  },
})

const wurzel = document.getElementById('wurzel')
if (!wurzel) {
  throw new Error('Das Element #wurzel fehlt in der index.html.')
}

createRoot(wurzel).render(
  <StrictMode>
    <QueryClientProvider client={abfragen}>
      <BrowserRouter>
        <SitzungProvider>
          <AppRouten />
        </SitzungProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
