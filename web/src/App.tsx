import { useRoute } from './hooks/useRoute';
import { Layout } from './components/Layout';
import { HomePage } from './pages/HomePage';
import { JobPage } from './pages/JobPage';

export default function App() {
  const [route, navigate] = useRoute();
  return (
    <Layout navigate={navigate}>
      {route.name === 'home' && <HomePage navigate={navigate} />}
      {route.name === 'job' && <JobPage jobId={route.jobId} navigate={navigate} />}
      {route.name === 'notfound' && (
        <section className="card">
          <h1>Page not found</h1>
          <p>
            There is nothing at <code>{route.path}</code>.{' '}
            <a href="/" onClick={(e) => { e.preventDefault(); navigate('/'); }}>Back to the start page</a>.
          </p>
        </section>
      )}
    </Layout>
  );
}
