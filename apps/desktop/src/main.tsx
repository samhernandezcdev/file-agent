import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import { queryClient } from "./lib/queryClient";

function renderApp(): void {
  ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
    <React.StrictMode>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </React.StrictMode>,
  );
}

// E2E-only: bridges WebdriverIO's tauri-service to this webview. Never
// imported outside an E2E build (VITE_E2E is only ever set by
// `pnpm --filter desktop e2e`) -- a normal dev/release build never pulls
// this in at all.
//
// AWAITED before the app renders at all -- a fire-and-forget import here
// let the app become interactive (and the native folder-picker button
// clickable) before the plugin had installed its invoke-interception
// hook, so `browser.tauri.mock()` never actually caught the call and a
// REAL native dialog opened instead (traced via a live E2E run: the
// dialog defaulted to a real, unrelated Downloads subfolder, which then
// got registered and read-only-analyzed -- never mutated, but a real
// violation of "isolated fixtures only" that this fix closes).
if (import.meta.env.VITE_E2E === "true") {
  import("@wdio/tauri-plugin").then(renderApp);
} else {
  renderApp();
}
