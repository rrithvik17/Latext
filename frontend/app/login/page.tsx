'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { api } from '@/services/api';
import { useAuth } from '@/components/auth/AuthProvider';
import { MessageSquare, Clock, Eye, EyeOff, Loader2, ArrowRight, Sparkles, CheckCircle2 } from 'lucide-react';

export default function LoginPage() {
  const { login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (!email || !password) {
      setError('Please provide both your email address and password.');
      return;
    }

    setSubmitting(true);
    try {
      const response = await api.login({ email: email.trim().toLowerCase(), password });
      await login(response.access_token);
    } catch (err: any) {
      const msg = err.message || '';
      if (msg.includes('Incorrect') || msg.includes('401') || msg.includes('validate credentials') || msg.includes('Not authenticated')) {
        setError('Invalid email or password. Please verify your credentials and try again.');
      } else if (msg.includes('Failed to fetch') || msg.includes('NetworkError')) {
        setError('Unable to reach the server. Please check your network connection.');
      } else {
        setError(msg || 'Login failed. Please try again.');
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleQuickLogin = (demoEmail: string, demoPass: string) => {
    setEmail(demoEmail);
    setPassword(demoPass);
    setError('');
  };

  return (
    <div className="min-h-screen flex flex-col justify-center items-center bg-slate-950 px-4 py-12 relative overflow-hidden">
      {/* Background glow accents */}
      <div className="absolute top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 w-96 h-96 bg-brand-500/10 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute bottom-10 right-10 w-64 h-64 bg-amber-500/5 rounded-full blur-3xl pointer-events-none" />

      <div className="w-full max-w-md relative z-10 space-y-6">
        {/* Brand Header */}
        <div className="text-center space-y-3">
          <div className="inline-flex items-center justify-center w-14 h-14 bg-gradient-to-tr from-brand-600 to-brand-500 rounded-2xl shadow-xl shadow-brand-500/20 mb-1 relative group">
            <MessageSquare className="w-7 h-7 text-white" />
            <div className="absolute -top-1 -right-1 w-4 h-4 bg-amber-400 rounded-full flex items-center justify-center border-2 border-slate-950 shadow-sm">
              <Clock className="w-2.5 h-2.5 text-slate-950" />
            </div>
          </div>
          <h1 className="text-3xl font-extrabold tracking-tight text-white">
            LATEXT
          </h1>
          <p className="text-sm text-slate-400 max-w-xs mx-auto">
            Messages, exactly when they matter.
          </p>
        </div>

        {/* Login Card */}
        <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-7 shadow-2xl backdrop-blur-md space-y-5">
          {error && (
            <div className="p-3.5 bg-red-500/10 border border-red-500/20 text-red-300 text-xs rounded-xl text-center leading-relaxed">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1.5" htmlFor="email-input">
                Email Address
              </label>
              <input
                id="email-input"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full bg-slate-950 border border-slate-800 focus:border-brand-500 focus:ring-1 focus:ring-brand-500/50 text-white rounded-xl px-3.5 py-2.5 text-sm transition-colors outline-none"
                placeholder="name@example.com"
                autoComplete="email"
                required
              />
            </div>

            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400" htmlFor="password-input">
                  Password
                </label>
              </div>
              <div className="relative">
                <input
                  id="password-input"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 focus:border-brand-500 focus:ring-1 focus:ring-brand-500/50 text-white rounded-xl pl-3.5 pr-10 py-2.5 text-sm transition-colors outline-none"
                  placeholder="••••••••"
                  autoComplete="current-password"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 transition-colors"
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={submitting}
              className="w-full bg-brand-500 hover:bg-brand-600 active:bg-brand-700 text-white rounded-xl py-3 font-semibold text-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-brand-500/25 flex items-center justify-center space-x-2"
            >
              {submitting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Signing In...</span>
                </>
              ) : (
                <>
                  <span>Sign In</span>
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </form>

          {/* Quick Demo Pre-fills */}
          <div className="pt-3 border-t border-slate-800/80">
            <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
              <span className="font-semibold uppercase tracking-wider text-[10px] text-slate-500 flex items-center gap-1">
                <Sparkles className="w-3 h-3 text-amber-400" /> Quick Demo Accounts
              </span>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => handleQuickLogin('alice@example.com', 'password123')}
                className="px-3 py-2 bg-slate-950/60 hover:bg-slate-800 border border-slate-800 rounded-xl text-left text-xs transition-colors group"
              >
                <div className="font-semibold text-slate-200 group-hover:text-white">Alice (Sender)</div>
                <div className="text-[10px] text-slate-500">alice@example.com</div>
              </button>
              <button
                type="button"
                onClick={() => handleQuickLogin('bob@example.com', 'password123')}
                className="px-3 py-2 bg-slate-950/60 hover:bg-slate-800 border border-slate-800 rounded-xl text-left text-xs transition-colors group"
              >
                <div className="font-semibold text-slate-200 group-hover:text-white">Bob (Recipient)</div>
                <div className="text-[10px] text-slate-500">bob@example.com</div>
              </button>
            </div>
          </div>

          <div className="text-center text-xs text-slate-400 pt-1">
            New to Latext?{' '}
            <Link href="/register" className="text-brand-400 hover:text-brand-300 font-semibold underline underline-offset-4">
              Create an account
            </Link>
          </div>
        </div>

        {/* Feature Highlights Footer */}
        <div className="flex items-center justify-center gap-4 text-[11px] text-slate-400">
          <span className="flex items-center gap-1">
            <CheckCircle2 className="w-3 h-3 text-emerald-400" /> Real-Time Chat
          </span>
          <span className="flex items-center gap-1">
            <CheckCircle2 className="w-3 h-3 text-emerald-400" /> Timezone Scheduling
          </span>
          <span className="flex items-center gap-1">
            <CheckCircle2 className="w-3 h-3 text-emerald-400" /> Outbox Guaranteed
          </span>
        </div>
      </div>
    </div>
  );
}
