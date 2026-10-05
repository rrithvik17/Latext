'use client';

import React, { useState, useEffect } from 'react';
import { Calendar, Clock, Globe, X, AlertCircle, Sparkles, Send, Loader2 } from 'lucide-react';
import { User } from '@/types';

interface ScheduleDialogProps {
  isOpen: boolean;
  onClose: () => void;
  messagePreview: string;
  recipient: User | null;
  onConfirm: (scheduledAt: string, timezone: string) => Promise<void>;
}

const POPULAR_TIMEZONES = [
  { value: 'UTC', label: 'UTC — Coordinated Universal Time' },
  { value: 'Europe/Stockholm', label: 'Europe/Stockholm (CET/CEST)' },
  { value: 'Europe/London', label: 'Europe/London (GMT/BST)' },
  { value: 'Europe/Berlin', label: 'Europe/Berlin (CET/CEST)' },
  { value: 'Europe/Paris', label: 'Europe/Paris (CET/CEST)' },
  { value: 'Europe/Copenhagen', label: 'Europe/Copenhagen (CET/CEST)' },
  { value: 'America/New_York', label: 'America/New York (EST/EDT - US Eastern)' },
  { value: 'America/Chicago', label: 'America/Chicago (CST/CDT - US Central)' },
  { value: 'America/Denver', label: 'America/Denver (MST/MDT - US Mountain)' },
  { value: 'America/Los_Angeles', label: 'America/Los Angeles (PST/PDT - US Pacific)' },
  { value: 'Asia/Kolkata', label: 'Asia/Kolkata (IST - India Standard Time)' },
  { value: 'Asia/Dubai', label: 'Asia/Dubai (GST - Gulf Standard Time)' },
  { value: 'Asia/Singapore', label: 'Asia/Singapore (SGT)' },
  { value: 'Asia/Tokyo', label: 'Asia/Tokyo (JST - Japan Standard Time)' },
  { value: 'Australia/Sydney', label: 'Australia/Sydney (AEST/AEDT)' },
];

export const ScheduleDialog: React.FC<ScheduleDialogProps> = ({
  isOpen,
  onClose,
  messagePreview,
  recipient,
  onConfirm,
}) => {
  const getTodayString = () => {
    const today = new Date();
    const yyyy = today.getFullYear();
    const mm = String(today.getMonth() + 1).padStart(2, '0');
    const dd = String(today.getDate()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd}`;
  };

  const getDefaultTime = () => {
    const now = new Date();
    now.setHours(now.getHours() + 1);
    now.setMinutes(0);
    const hh = String(now.getHours()).padStart(2, '0');
    const mm = String(now.getMinutes()).padStart(2, '0');
    return `${hh}:${mm}`;
  };

  const [date, setDate] = useState(getTodayString());
  const [time, setTime] = useState(getDefaultTime());
  const [timezone, setTimezone] = useState('UTC');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [availableTimezones, setAvailableTimezones] = useState(POPULAR_TIMEZONES);

  // Auto-detect browser timezone
  useEffect(() => {
    try {
      const systemTz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      if (systemTz) {
        const exists = POPULAR_TIMEZONES.some((tz) => tz.value === systemTz);
        if (!exists) {
          setAvailableTimezones([{ value: systemTz, label: `${systemTz} (Detected Local)` }, ...POPULAR_TIMEZONES]);
        }
        setTimezone(systemTz);
      }
    } catch (e) {
      console.warn('Failed to detect system timezone', e);
    }
  }, []);

  // Reset states when opening
  useEffect(() => {
    if (isOpen) {
      setError(null);
      setSubmitting(false);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!date || !time) {
      setError('Please select both a date and a time.');
      return;
    }

    if (!messagePreview.trim()) {
      setError('Message content cannot be empty.');
      return;
    }

    const selectedLocalStr = `${date}T${time}:00`;
    
    // Quick client-side check if timezone is browser's local timezone
    try {
      const systemTz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      if (timezone === systemTz) {
        const selectedDate = new Date(selectedLocalStr);
        if (selectedDate.getTime() <= Date.now() + 10000) {
          setError('Scheduled delivery time must be in the future (at least 15-30 seconds ahead).');
          return;
        }
      }
    } catch {
      // Pass to server validator
    }

    setSubmitting(true);
    try {
      await onConfirm(selectedLocalStr, timezone);
    } catch (err: any) {
      setError(err.message || 'Failed to schedule message.');
      setSubmitting(false);
    }
  };

  // Human preview calculation
  const formatScheduledPreview = () => {
    if (!date || !time) return '';
    try {
      const [year, month, day] = date.split('-').map(Number);
      const [hour, min] = time.split(':').map(Number);
      const d = new Date(year, month - 1, day, hour, min);
      const dateStr = d.toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
      });
      return `${dateStr} at ${time} (${timezone})`;
    } catch {
      return `${date} ${time} (${timezone})`;
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-md animate-in fade-in duration-200">
      <div className="w-full max-w-lg bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl overflow-hidden animate-in zoom-in-95 duration-200">
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-slate-800 bg-slate-950/40">
          <div className="flex items-center space-x-3">
            <div className="w-9 h-9 bg-brand-500/10 border border-brand-500/20 text-brand-400 rounded-xl flex items-center justify-center">
              <Clock className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-bold text-white">Schedule Message</h3>
              <p className="text-xs text-slate-400">Deliver automatically at a chosen future time</p>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={submitting}
            className="p-1.5 hover:bg-slate-800 rounded-lg text-slate-400 hover:text-slate-200 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content Form */}
        <form onSubmit={handleSubmit} className="p-6 space-y-5">
          {/* Recipient Context */}
          {recipient && (
            <div className="flex items-center justify-between p-3 bg-slate-950/60 border border-slate-800/80 rounded-xl text-xs">
              <span className="text-slate-400 font-medium">Send to:</span>
              <div className="flex items-center space-x-2 font-semibold text-slate-200">
                <span>{recipient.display_name}</span>
                <span className="text-slate-500 font-normal">(@{recipient.username})</span>
              </div>
            </div>
          )}

          {/* Message Content Preview */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Message Content
            </label>
            <div className="p-3.5 bg-slate-950 border border-slate-800 rounded-xl max-h-24 overflow-y-auto text-xs text-slate-200 leading-relaxed break-words whitespace-pre-wrap">
              "{messagePreview}"
            </div>
          </div>

          {/* Date & Time Pickers */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
                <Calendar className="w-3.5 h-3.5 text-slate-400" /> Date
              </label>
              <input
                type="date"
                min={getTodayString()}
                value={date}
                onChange={(e) => setDate(e.target.value)}
                disabled={submitting}
                className="w-full bg-slate-950 border border-slate-800 focus:border-brand-500 focus:ring-1 focus:ring-brand-500/50 rounded-xl px-3.5 py-2.5 text-xs text-slate-200 transition-colors outline-none cursor-pointer"
                required
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
                <Clock className="w-3.5 h-3.5 text-slate-400" /> Time
              </label>
              <input
                type="time"
                value={time}
                onChange={(e) => setTime(e.target.value)}
                disabled={submitting}
                className="w-full bg-slate-950 border border-slate-800 focus:border-brand-500 focus:ring-1 focus:ring-brand-500/50 rounded-xl px-3.5 py-2.5 text-xs text-slate-200 transition-colors outline-none cursor-pointer"
                required
              />
            </div>
          </div>

          {/* Timezone Selector */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
              <Globe className="w-3.5 h-3.5 text-slate-400" /> Target Timezone
            </label>
            <select
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
              disabled={submitting}
              className="w-full bg-slate-950 border border-slate-800 focus:border-brand-500 focus:ring-1 focus:ring-brand-500/50 rounded-xl px-3.5 py-2.5 text-xs text-slate-200 transition-colors outline-none cursor-pointer"
            >
              {availableTimezones.map((tz) => (
                <option key={tz.value} value={tz.value} className="bg-slate-900 text-slate-200">
                  {tz.label}
                </option>
              ))}
            </select>
          </div>

          {/* Live Delivery Preview Banner */}
          {date && time && (
            <div className="p-3 bg-brand-500/5 border border-brand-500/20 rounded-xl flex items-center space-x-2 text-xs text-brand-300">
              <Sparkles className="w-4 h-4 text-brand-400 shrink-0" />
              <span>
                Delivering on <strong>{formatScheduledPreview()}</strong>
              </span>
            </div>
          )}

          {/* Error Feedback */}
          {error && (
            <div className="p-3.5 bg-red-500/10 border border-red-500/20 rounded-xl text-xs text-red-300 flex items-start gap-2 leading-relaxed">
              <AlertCircle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          {/* Action Buttons */}
          <div className="flex items-center justify-end space-x-3 pt-3 border-t border-slate-800">
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className="px-4 py-2.5 rounded-xl border border-slate-800 hover:bg-slate-800 text-xs font-medium text-slate-300 hover:text-slate-100 transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting || !messagePreview.trim()}
              className="px-5 py-2.5 rounded-xl bg-brand-500 hover:bg-brand-600 active:bg-brand-700 text-xs font-semibold text-white shadow-lg shadow-brand-500/25 transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center space-x-2"
            >
              {submitting ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  <span>Scheduling...</span>
                </>
              ) : (
                <>
                  <Clock className="w-3.5 h-3.5" />
                  <span>Schedule Message</span>
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
