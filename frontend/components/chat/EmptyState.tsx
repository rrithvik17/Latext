'use client';

import React from 'react';
import { MessageSquare, Clock, Globe, ShieldCheck, Zap, Menu } from 'lucide-react';

interface EmptyStateProps {
  onOpenSidebarMobile?: () => void;
}

export default function EmptyState({ onOpenSidebarMobile }: EmptyStateProps) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center bg-slate-950 p-6 md:p-10 text-center select-none overflow-y-auto relative">
      {/* Mobile Top Bar */}
      {onOpenSidebarMobile && (
        <div className="md:hidden absolute top-4 left-4">
          <button
            onClick={onOpenSidebarMobile}
            className="p-2 bg-slate-900 border border-slate-800 rounded-xl text-slate-300 hover:text-white flex items-center gap-1.5 text-xs"
          >
            <Menu className="w-4 h-4" />
            <span>Conversations</span>
          </button>
        </div>
      )}

      {/* Hero Badge */}
      <div className="w-16 h-16 bg-gradient-to-tr from-brand-600 to-brand-500 rounded-3xl flex items-center justify-center mb-5 shadow-2xl shadow-brand-500/25 relative group">
        <MessageSquare className="w-8 h-8 text-white group-hover:scale-105 transition-transform" />
        <div className="absolute -top-1 -right-1 w-5 h-5 bg-amber-400 rounded-full flex items-center justify-center border-2 border-slate-950 shadow-md">
          <Clock className="w-3 h-3 text-slate-950" />
        </div>
      </div>

      <h2 className="text-2xl md:text-3xl font-extrabold tracking-tight text-white mb-2">
        Welcome to LATEXT
      </h2>
      <p className="text-slate-400 text-sm max-w-md mb-8 leading-relaxed">
        "Messages, exactly when they matter."<br />
        Real-time chat paired with timezone-aware scheduled delivery.
      </p>

      {/* 5-Step Product Workflow */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 max-w-2xl w-full text-left mb-8">
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3.5 space-y-1.5 shadow-sm">
          <div className="flex items-center space-x-2 text-brand-400 font-bold text-xs">
            <span className="w-5 h-5 rounded-full bg-brand-500/15 flex items-center justify-center text-[10px]">1</span>
            <span>Find Teammate</span>
          </div>
          <p className="text-[11px] text-slate-400 leading-snug">
            Search users in the sidebar to open or initiate a chat.
          </p>
        </div>

        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3.5 space-y-1.5 shadow-sm">
          <div className="flex items-center space-x-2 text-brand-400 font-bold text-xs">
            <span className="w-5 h-5 rounded-full bg-brand-500/15 flex items-center justify-center text-[10px]">2</span>
            <span>Send or Schedule</span>
          </div>
          <p className="text-[11px] text-slate-400 leading-snug">
            Send instantly with <strong>Enter</strong>, or click <strong>Clock</strong> to schedule.
          </p>
        </div>

        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3.5 space-y-1.5 shadow-sm">
          <div className="flex items-center space-x-2 text-brand-400 font-bold text-xs">
            <span className="w-5 h-5 rounded-full bg-brand-500/15 flex items-center justify-center text-[10px]">3</span>
            <span>Timezone Aware</span>
          </div>
          <p className="text-[11px] text-slate-400 leading-snug">
            Set target delivery in any IANA timezone with DST safety.
          </p>
        </div>

        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3.5 space-y-1.5 shadow-sm">
          <div className="flex items-center space-x-2 text-brand-400 font-bold text-xs">
            <span className="w-5 h-5 rounded-full bg-brand-500/15 flex items-center justify-center text-[10px]">4</span>
            <span>Track Delivery</span>
          </div>
          <p className="text-[11px] text-slate-400 leading-snug">
            Monitor real-time status: Sent (✓), Delivered (✓✓), Read (✓✓).
          </p>
        </div>
      </div>

      {/* Value Badges */}
      <div className="flex flex-wrap items-center justify-center gap-3 text-xs text-slate-400">
        <div className="flex items-center gap-1.5 bg-slate-900 border border-slate-800 px-3 py-1.5 rounded-full">
          <Zap className="w-3.5 h-3.5 text-amber-400" />
          <span>Distributed WebSocket Routing</span>
        </div>
        <div className="flex items-center gap-1.5 bg-slate-900 border border-slate-800 px-3 py-1.5 rounded-full">
          <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
          <span>Transactional Outbox Reliability</span>
        </div>
      </div>
    </div>
  );
}
