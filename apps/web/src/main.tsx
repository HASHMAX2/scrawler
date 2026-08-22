import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "./index.css";
import { Layout } from "./components/Layout";
import { FilterProvider } from "./state/FilterContext";
import { ThemeProvider } from "./state/ThemeContext";
import { Overview } from "./pages/Overview";
import { IntelligenceMap } from "./pages/IntelligenceMap";
import { Sales } from "./pages/Sales";
import { Rentals } from "./pages/Rentals";
import { UnitTypes } from "./pages/UnitTypes";
import { Areas } from "./pages/Areas";
import { AreaDetail } from "./pages/AreaDetail";
import { Communities } from "./pages/Communities";
import { CommunityDetail } from "./pages/CommunityDetail";
import { Compare } from "./pages/Compare";
import { MapPage } from "./pages/MapPage";
import { Explorer } from "./pages/Explorer";
import { ImportData } from "./pages/ImportData";
import { DataQuality } from "./pages/DataQuality";
import { Projects } from "./pages/Projects";
import { ProjectIntelligence } from "./pages/ProjectIntelligence";
import { Developers } from "./pages/Developers";
import { Supply } from "./pages/Supply";
import { ConstructionWatch } from "./pages/ConstructionWatch";
import { Opportunities } from "./pages/Opportunities";
import { MarketSignals } from "./pages/MarketSignals";
import { DecisionEngine } from "./pages/DecisionEngine";
import { Reels } from "./pages/Reels";
import { ReelWorkspace } from "./pages/ReelWorkspace";

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 60_000, retry: 1 } } });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
      <FilterProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<Layout />}>
              <Route path="/" element={<Overview />} />
              <Route path="/intelligence-map" element={<IntelligenceMap />} />
              <Route path="/sales" element={<Sales />} />
              <Route path="/rentals" element={<Rentals />} />
              <Route path="/unit-types" element={<UnitTypes />} />
              <Route path="/areas" element={<Areas />} />
              <Route path="/areas/:areaId" element={<AreaDetail />} />
              <Route path="/communities" element={<Communities />} />
              <Route path="/communities/:key" element={<CommunityDetail />} />
              <Route path="/projects" element={<Projects />} />
              <Route path="/projects/:slug" element={<ProjectIntelligence />} />
              <Route path="/projects/:slug/buildings/:buildingSlug" element={<ProjectIntelligence />} />
              <Route path="/developers" element={<Developers />} />
              <Route path="/supply" element={<Supply />} />
              <Route path="/construction-watch" element={<ConstructionWatch />} />
              <Route path="/compare" element={<Compare />} />
              <Route path="/opportunities" element={<Opportunities />} />
              <Route path="/signals" element={<MarketSignals />} />
              <Route path="/decision-engine" element={<DecisionEngine />} />
              <Route path="/reels" element={<Reels />} />
              <Route path="/reels/:id" element={<ReelWorkspace />} />
              <Route path="/map" element={<MapPage />} />
              <Route path="/explorer" element={<Explorer />} />
              <Route path="/import" element={<ImportData />} />
              <Route path="/data-quality" element={<DataQuality />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </FilterProvider>
      </ThemeProvider>
    </QueryClientProvider>
  </StrictMode>,
);
