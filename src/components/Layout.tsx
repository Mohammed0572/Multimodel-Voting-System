import { Outlet, Link } from 'react-router-dom';

const Layout = () => {

  return (
    <div className="min-h-screen bg-(--cream) flex flex-col">


      <main id="main" className="grow flex flex-col items-center p-4 sm:p-6 lg:p-8 w-full">
        <div className="w-full max-w-5xl grow flex flex-col">
          <Outlet />
        </div>
      </main>

      <div className="gov-footer mt-auto">
        <span>© {new Date().getFullYear()} Prajatantra e-Voting Platform</span>
        <span>
          <Link to="/terms">Terms</Link> · 
          <Link to="/privacy">Privacy</Link> · 
          <Link to="/accessibility">Accessibility</Link> · 
          <Link to="/contact">Contact</Link>
        </span>
      </div>
    </div>
  );
};

export default Layout;
