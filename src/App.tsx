import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import Navbar from './components/Navbar';
import Home from './pages/Home';
import VoterLogin from './pages/VoterLogin';
import Registration from './pages/Registration';
import AdminLogin from './pages/AdminLogin';
import Admin from './pages/Admin';
import Voting from './pages/Voting';
import Terms from './pages/Terms';
import Privacy from './pages/Privacy';
import Accessibility from './pages/Accessibility';
import Contact from './pages/Contact';
import { Web3Provider } from './context/Web3Context';
import { LanguageProvider } from './context/LanguageContext';
import { AuthProvider } from './context/AuthContext';
import ProtectedRoute from './components/ProtectedRoute';

function App() {
  return (
    <LanguageProvider>
      <AuthProvider>
        <Web3Provider>
          <BrowserRouter>
            <Navbar />
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/login" element={<VoterLogin />} />
              <Route path="/register" element={<Registration />} />
            <Route element={<ProtectedRoute allowedRole="user" />}>
              <Route path="/voting" element={<Voting />} />
            </Route>
            
            {/* Legacy Layout wrapper for Admin and static pages */}
            <Route element={<Layout />}>
              <Route path="/admin-login" element={<AdminLogin />} />
              <Route element={<ProtectedRoute allowedRole="admin" />}>
                <Route path="/admin" element={<Admin />} />
              </Route>
              <Route path="/terms" element={<Terms />} />
              <Route path="/privacy" element={<Privacy />} />
              <Route path="/accessibility" element={<Accessibility />} />
              <Route path="/contact" element={<Contact />} />
            </Route>
          </Routes>
          </BrowserRouter>
        </Web3Provider>
      </AuthProvider>
    </LanguageProvider>
  );
}

export default App;

