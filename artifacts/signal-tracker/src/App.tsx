import { type ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Route, Switch, useLocation, Router as WouterRouter } from 'wouter';
import { useHashLocation } from 'wouter/use-hash-location';
import { ErrorBoundary } from '@/components/error-boundary';
import { Toaster } from '@/components/ui/toaster';
import { TooltipProvider } from '@/components/ui/tooltip';
import { Shell } from '@/components/shell';
import NotFound from '@/pages/not-found';
import GoldBoardPage from '@/pages/gold-board';
import LivePage from '@/pages/live';
import HistoryPage from '@/pages/history';
import ScoreboardPage from '@/pages/scoreboard';
import StrategiesPage from '@/pages/strategies';
import StrategyDetailPage from '@/pages/strategy-detail';
import ComparePage from '@/pages/compare';
import AboutPage from '@/pages/about';
import TelegramPage from '@/pages/telegram';

const queryClient = new QueryClient();

function Router() {
  return (
    <Shell>
      <RoutedErrorBoundary>
        <Switch>
          <Route path="/" component={GoldBoardPage} />
          <Route path="/signals" component={LivePage} />
          <Route path="/history" component={HistoryPage} />
          <Route path="/scoreboard" component={ScoreboardPage} />
          <Route path="/strategies" component={StrategiesPage} />
          <Route path="/strategies/:code" component={StrategyDetailPage} />
          <Route path="/compare" component={ComparePage} />
          <Route path="/about" component={AboutPage} />
          <Route path="/telegram" component={TelegramPage} />
          <Route component={NotFound} />
        </Switch>
      </RoutedErrorBoundary>
    </Shell>
  );
}

function RoutedErrorBoundary({ children }: { children: ReactNode }) {
  const [location] = useLocation();
  return <ErrorBoundary resetKey={location}>{children}</ErrorBoundary>;
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <WouterRouter hook={useHashLocation}>
          <Router />
        </WouterRouter>
        <Toaster />
      </TooltipProvider>
    </QueryClientProvider>
  );
}

export default App;
