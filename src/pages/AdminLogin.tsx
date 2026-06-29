import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLanguage } from '../context/LanguageContext';
import { useAuth, API_BASE } from '../context/AuthContext';
import { Eye, EyeOff } from 'lucide-react';

const AdminLogin = () => {
  const { t } = useLanguage();
  const { setAuth } = useAuth();
  const [adminId, setAdminId] = useState('');
  const [adminPassword, setAdminPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [status, setStatus] = useState({ message: '', type: '' });
  const [isProcessing, setIsProcessing] = useState<boolean>(false);
  
  const navigate = useNavigate();

  const updateStatus = (msg: string, type: string = 'info') => {
    setStatus({ message: msg, type });
  };

  const handlePaste = (e: React.ClipboardEvent<HTMLInputElement>) => {
    const pastedText = e.clipboardData.getData('text');
    if (pastedText.length > 64) {
      e.preventDefault();
      updateStatus("Input length exceeded maximum allowed limit.", "error");
    }
  };

  const adminLogin = async () => {
    if (!adminId.trim() || !adminPassword.trim()) {
      updateStatus("Please enter both Admin ID and Password.", "error");
      return;
    }

    setIsProcessing(true);
    updateStatus("Authenticating...", "info");

    try {
      const response = await fetch(`${API_BASE}/admin-login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include', // allow browser to store the HttpOnly cookie
        body: JSON.stringify({ 
          username: adminId, 
          password: adminPassword,
        })
      });

      if (response.ok) {
        const data = await response.json();
        if (data.role === 'admin') {
          updateStatus("Authentication successful. Redirecting...", "success");
          // Token is now stored in an HttpOnly cookie by the backend.
          // We just update React state with the non-sensitive session info.
          setAuth({ voter_id: data.voter_id, role: data.role });
          setTimeout(() => navigate('/admin'), 1000);
        } else {
          updateStatus("Access denied. Admin privileges required.", "error");
          setIsProcessing(false);
        }
      } else {
        const errData = await response.json().catch(() => ({}));
        updateStatus(`Failed: ${errData.detail || 'Invalid credentials.'}`, "error");
        setIsProcessing(false);
      }
    } catch (error) {
      updateStatus("Network error. Ensure backend is running.", "error");
      setIsProcessing(false);
    }
  };

  return (
    <div className="grow flex flex-col items-center justify-center w-full px-4 -mt-16 sm:-mt-24">
      <div className="w-full max-w-md overflow-hidden bg-white shadow-2xl shadow-black/5 rounded-2xl border border-gray-100">
        <div className="bg-gray-50 border-b border-gray-100 p-6 sm:p-8 text-center">
          <h2 className="text-2xl font-bold" style={{ color: 'var(--ink)' }}>{t('adminlogin.title')}</h2>
          <p className="text-sm mt-2 text-gray-500">{t('adminlogin.subtitle')}</p>
        </div>

      <div className="p-6 sm:p-8 space-y-5 fade-in">
        <div className="flex flex-col gap-1">
          <label htmlFor="adminId" className="font-medium text-sm">{t('adminlogin.id_label')}</label>
          <input
            id="adminId"
            type="text"
            value={adminId}
            onChange={(e) => setAdminId(e.target.value)}
            onPaste={handlePaste}
            placeholder={t('adminlogin.id_placeholder')}
            className="gov-input w-full"
            maxLength={64}
            autoComplete="off"
          />
        </div>
        
        <div className="flex flex-col gap-1">
          <label htmlFor="adminPassword" className="font-medium text-sm">Password</label>
          <div className="relative">
            <input
              id="adminPassword"
              type={showPassword ? "text" : "password"}
              value={adminPassword}
              onChange={(e) => setAdminPassword(e.target.value)}
              onPaste={handlePaste}
              placeholder="Enter Password"
              className="gov-input w-full pr-10"
              maxLength={64}
              autoComplete="off"
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-700 focus:outline-none"
            >
              {showPassword ? <EyeOff size={20} /> : <Eye size={20} />}
            </button>
          </div>
        </div>

        {status.message && (
          <div
            role={status.type === 'error' ? 'alert' : 'status'}
            aria-live={status.type === 'error' ? 'assertive' : 'polite'}
            className={`p-4 border-l-4 rounded-sm ${status.type === 'error' ? 'bg-[#FFF5F5] border-danger text-danger' : status.type === 'success' ? 'bg-india-green-light border-india-green text-india-green' : 'bg-india-blue-lt border-india-blue text-india-blue'}`}
          >
            <strong>{t('voter.status')}</strong> {status.message}
          </div>
        )}

        <div className="pt-2">
          <button
            onClick={adminLogin}
            disabled={isProcessing}
            className="btn-primary w-full justify-center disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isProcessing ? t('voter.processing') : t('adminlogin.login_btn')}
          </button>
        </div>
      </div>
      </div>
    </div>
  );
};

export default AdminLogin;
