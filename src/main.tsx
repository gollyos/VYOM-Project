import React from "react";
import ReactDOM from "react-dom/client";
import { VyomExperience } from "@/components/vyom-experience";
import { ErrorBoundary } from "@/components/error-boundary";
import "@/styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <VyomExperience />
    </ErrorBoundary>
  </React.StrictMode>,
);

