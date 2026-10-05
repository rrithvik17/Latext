'use client';

import React, { useState, useEffect } from 'react';
import { Clock, Trash2, Edit2, Check, X, AlertCircle, Loader2, Calendar, Globe, CheckCircle2, XCircle, ArrowUpRight } from 'lucide-react';
import { api } from '../../services/api';
import { ScheduledMessage, Conversation } from '../../types';

interface ScheduledListProps {
  conversations: Conversation[];
  currentUserId: string;
  onRefreshTrigger?: number;
  onSelectConversation?: (conversationId: string) => void;
  isOpenMobile?: boolean;
  onCloseMobile?: () => void;
}

const COMMON_TIMEZONES = [
  { value: 'UTC', label: 'UTC' },
  { value: 'Europe/Stockholm', label: 'Europe/Stockholm' },
  { value: 'Europe/London', label: 'Europe/London' },
  { value: 'Europe/Berlin', label: 'Europe/Berlin' },
  { value: 'Europe/Paris', label: 'Europe/Paris' },
  { value: 'Europe/Copenhagen', label: 'Europe/Copenhagen' },
  { value: 'America/New_York', label: 'America/New_York' },
  { value: 'America/Chicago', label: 'America/Chicago' },
  { value: 'America/Los_Angeles', label: 'America/Los_Angeles' },
  { value: 'Asia/Kolkata', label: 'Asia/Kolkata' },
  { value: 'Asia/Dubai', label: 'Asia/Dubai' },
  { value: 'Asia/Tokyo', label: 'Asia/Tokyo' },
  { value: 'Australia/Sydney', label: 'Australia/Sydney' },
];

export const ScheduledList: React.FC<ScheduledListProps> = ({
  conversations,
  currentUserId,
  onRefreshTrigger = 0,
  onSelectConversation,
  isOpenMobile = false,
  onCloseMobile,
}) => {
  const [scheduledMessages, setScheduledMessages] = useState<ScheduledMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState<string | null>(null);
  
  // Inline edit fields
  const [editContent, setEditContent] = useState('');
  const [editDate, setEditDate] = useState('');
  const [editTime, setEditTime] = useState('');
  const [editTimezone, setEditTimezone] = useState('');
  const [editError, setEditError] = useState<string | null>(null);
  const [savingEdit, setSavingEdit] = useState(false);

  // Cancellation state
  const [cancellingItem, setCancellingItem] = useState<ScheduledMessage | null>(null);
  const [cancellingLoading, setCancellingLoading] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);

  const fetchScheduled = async () => {
    try {
      const data = await api.getScheduledMessages();
      setScheduledMessages(data);
    } catch (e) {
      console.error('Failed to fetch scheduled messages', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchScheduled();
    const interval = setInterval(fetchScheduled, 6000);
    return () => clearInterval(interval);
  }, [onRefreshTrigger]);

  const getRecipientName = (conversationId: string) => {
    const conv = conversations.find((c) => c.id === conversationId);
    if (!conv) return 'Recipient';
    const otherParticipant = conv.participants.find((p) => p.user_id !== currentUserId);
    return otherParticipant?.user.display_name || otherParticipant?.user.username || 'Recipient';
  };

  const handleStartEdit = (msg: ScheduledMessage) => {
    setEditingId(msg.id);
    setEditContent(msg.content);
    setEditTimezone(msg.timezone || 'UTC');
    setEditError(null);

    const today = new Date();
    const yyyy = today.getFullYear();
    const mm = String(today.getMonth() + 1).padStart(2, '0');
    const dd = String(today.getDate()).padStart(2, '0');
    setEditDate(`${yyyy}-${mm}-${dd}`);
    
    today.setHours(today.getHours() + 1);
    const hh = String(today.getHours()).padStart(2, '0');
    const min = String(today.getMinutes()).padStart(2, '0');
    setEditTime(`${hh}:${min}`);
  };

  const handleSaveEdit = async (id: string) => {
    setEditError(null);
    if (!editContent.trim()) {
      setEditError('Message content cannot be empty.');
      return;
    }

    if (!editDate || !editTime) {
      setEditError('Please specify date and time.');
      return;
    }

    setSavingEdit(true);
    try {
      const selectedLocalStr = `${editDate}T${editTime}:00`;
      await api.updateScheduledMessage(id, {
        content: editContent.trim(),
        scheduled_at: selectedLocalStr,
        timezone: editTimezone,
      });

      setEditingId(null);
      await fetchScheduled();
    } catch (e: any) {
      setEditError(e.message || 'Failed to update scheduled message.');
    } finally {
      setSavingEdit(false);
    }
  };

  const handleConfirmCancel = async () => {
    if (!cancellingItem) return;
    setCancellingLoading(true);
    setCancelError(null);

    try {
      await api.cancelScheduledMessage(cancellingItem.id);
      setCancellingItem(null);
      await fetchScheduled();
    } catch (e: any) {
      setCancelError(e.message || 'Failed to cancel scheduled message.');
    } finally {
      setCancellingLoading(false);
    }
  };

  const getStatusBadge = (status: ScheduledMessage['status']) => {
    switch (status) {
      case 'SCHEDULED':
        return (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-blue-500/10 text-blue-400 border border-blue-500/20 flex items-center gap-1">
            <Clock className="w-2.5 h-2.5" /> Scheduled
          </span>
        );
      case 'PROCESSING':
        return (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20 flex items-center gap-1 animate-pulse">
            <Loader2 className="w-2.5 h-2.5 animate-spin" /> Processing
          </span>
        );
      case 'SENT':
        return (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1">
            <CheckCircle2 className="w-2.5 h-2.5" /> Delivered
          </span>
        );
      case 'CANCELLED':
        return (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-slate-800 text-slate-400 border border-slate-700/50 flex items-center gap-1">
            <XCircle className="w-2.5 h-2.5" /> Cancelled
          </span>
        );
      case 'FAILED':
        return (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-red-500/10 text-red-400 border border-red-500/20 flex items-center gap-1">
            <AlertCircle className="w-2.5 h-2.5" /> Failed
          </span>
        );
    }
  };

  const formatScheduledDisplay = (utcStr: string, tz: string) => {
    try {
      const dt = new Date(utcStr);
      return dt.toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return utcStr;
    }
  };

  return (
    <div
      className={`flex flex-col h-full bg-slate-900/90 border-l border-slate-800/80 w-80 shrink-0 transition-transform duration-200 z-30 ${
        isOpenMobile ? 'fixed inset-y-0 right-0 max-w-[85vw] shadow-2xl' : 'hidden md:flex'
      }`}
    >
      {/* Title Header */}
      <div className="flex items-center justify-between p-4 border-b border-slate-800 bg-slate-950/40">
        <div className="flex items-center space-x-2">
          <Clock className="w-4 h-4 text-brand-400" />
          <h2 className="text-xs font-bold text-white uppercase tracking-wider">
            Scheduled Queue
          </h2>
        </div>
        <div className="flex items-center space-x-1.5">
          <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-brand-500/10 text-brand-300 border border-brand-500/20">
            {scheduledMessages.filter((m) => m.status === 'SCHEDULED').length} active
          </span>
          {onCloseMobile && (
            <button
              onClick={onCloseMobile}
              className="md:hidden p-1 text-slate-400 hover:text-white"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {/* List Container */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2.5">
        {loading && scheduledMessages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 space-y-2 text-xs text-slate-500">
            <Loader2 className="w-5 h-5 text-brand-500 animate-spin" />
            <span>Loading scheduled feed...</span>
          </div>
        ) : scheduledMessages.length === 0 ? (
          <div className="flex flex-col items-center justify-center text-center h-64 px-4 text-slate-500 space-y-3">
            <div className="w-12 h-12 rounded-2xl bg-slate-950 border border-slate-800 flex items-center justify-center">
              <Clock className="w-6 h-6 text-slate-600" />
            </div>
            <div>
              <p className="text-xs font-semibold text-slate-300">No scheduled messages</p>
              <p className="text-[11px] text-slate-500 mt-1 leading-relaxed">
                Schedule a message and Latext will deliver it automatically at the exact time you choose.
              </p>
            </div>
          </div>
        ) : (
          scheduledMessages.map((msg) => {
            const isEditing = editingId === msg.id;

            return (
              <div
                key={msg.id}
                className="bg-slate-950/70 border border-slate-800/90 rounded-xl p-3 space-y-2 hover:border-slate-700/80 transition-all shadow-sm"
              >
                {/* Header Info */}
                <div className="flex items-start justify-between gap-2">
                  <div className="flex flex-col min-w-0">
                    <button
                      type="button"
                      onClick={() => onSelectConversation && onSelectConversation(msg.conversation_id)}
                      className="text-xs font-bold text-slate-200 hover:text-brand-400 text-left truncate flex items-center gap-1 group"
                    >
                      <span className="truncate">To: {getRecipientName(msg.conversation_id)}</span>
                      <ArrowUpRight className="w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
                    </button>
                    <span className="text-[10px] text-slate-400 mt-0.5 flex items-center gap-1">
                      <span>{formatScheduledDisplay(msg.scheduled_at_utc, msg.timezone)}</span>
                      <span className="text-slate-500 font-mono text-[9px]">({msg.timezone})</span>
                    </span>
                  </div>
                  {getStatusBadge(msg.status)}
                </div>

                {/* Edit Form */}
                {isEditing ? (
                  <div className="space-y-2.5 p-2.5 bg-slate-900 border border-slate-800 rounded-lg text-xs">
                    <textarea
                      value={editContent}
                      onChange={(e) => setEditContent(e.target.value)}
                      disabled={savingEdit}
                      className="w-full bg-slate-950 border border-slate-800 focus:border-brand-500 rounded-lg p-2 text-xs text-slate-200 resize-none h-16 outline-none"
                    />

                    <div className="grid grid-cols-2 gap-1.5">
                      <input
                        type="date"
                        value={editDate}
                        onChange={(e) => setEditDate(e.target.value)}
                        disabled={savingEdit}
                        className="bg-slate-950 border border-slate-800 focus:border-brand-500 rounded-lg p-1.5 text-[11px] text-slate-200 outline-none"
                      />
                      <input
                        type="time"
                        value={editTime}
                        onChange={(e) => setEditTime(e.target.value)}
                        disabled={savingEdit}
                        className="bg-slate-950 border border-slate-800 focus:border-brand-500 rounded-lg p-1.5 text-[11px] text-slate-200 outline-none"
                      />
                    </div>

                    <select
                      value={editTimezone}
                      onChange={(e) => setEditTimezone(e.target.value)}
                      disabled={savingEdit}
                      className="w-full bg-slate-950 border border-slate-800 focus:border-brand-500 rounded-lg p-1.5 text-[10px] text-slate-200 outline-none"
                    >
                      {COMMON_TIMEZONES.map((tz) => (
                        <option key={tz.value} value={tz.value} className="bg-slate-900">
                          {tz.label}
                        </option>
                      ))}
                    </select>

                    {editError && (
                      <div className="text-[10px] text-red-400 p-1.5 bg-red-500/10 border border-red-500/20 rounded flex items-start gap-1 leading-tight">
                        <AlertCircle className="w-3 h-3 shrink-0 mt-0.5" />
                        <span>{editError}</span>
                      </div>
                    )}

                    <div className="flex items-center justify-end space-x-2 pt-1 border-t border-slate-800">
                      <button
                        onClick={() => setEditingId(null)}
                        disabled={savingEdit}
                        className="px-2.5 py-1 text-slate-400 hover:text-slate-200 text-xs font-medium rounded hover:bg-slate-800"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={() => handleSaveEdit(msg.id)}
                        disabled={savingEdit}
                        className="px-3 py-1 bg-brand-500 hover:bg-brand-600 text-white text-xs font-semibold rounded flex items-center gap-1 shadow-sm disabled:opacity-50"
                      >
                        {savingEdit ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
                        <span>Save</span>
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <p className="text-xs text-slate-300 break-words leading-relaxed whitespace-pre-wrap">
                      "{msg.content}"
                    </p>

                    {/* Failure details if relevant */}
                    {msg.status === 'FAILED' && msg.failure_reason && (
                      <div className="text-[10px] bg-red-500/10 border border-red-500/20 p-2 rounded-lg text-red-300 leading-tight">
                        <strong>Failure:</strong> {msg.failure_reason}
                      </div>
                    )}

                    {/* Card Actions */}
                    {msg.status === 'SCHEDULED' && (
                      <div className="flex items-center justify-end space-x-3 pt-1.5 border-t border-slate-800/60">
                        <button
                          onClick={() => handleStartEdit(msg)}
                          className="flex items-center gap-1 text-[11px] text-slate-400 hover:text-slate-200 transition-colors"
                        >
                          <Edit2 className="w-3 h-3" /> Edit
                        </button>
                        <button
                          onClick={() => {
                            setCancellingItem(msg);
                            setCancelError(null);
                          }}
                          className="flex items-center gap-1 text-[11px] text-red-400 hover:text-red-300 transition-colors"
                        >
                          <Trash2 className="w-3 h-3" /> Cancel
                        </button>
                      </div>
                    )}
                  </>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* Cancel Confirmation Modal */}
      {cancellingItem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-in fade-in duration-150">
          <div className="w-full max-w-sm bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-2xl space-y-4 animate-in zoom-in-95 duration-150">
            <div className="flex items-center space-x-3 text-red-400">
              <div className="w-9 h-9 rounded-xl bg-red-500/10 border border-red-500/20 flex items-center justify-center">
                <Trash2 className="w-5 h-5" />
              </div>
              <h3 className="text-sm font-bold text-white">Cancel Scheduled Message?</h3>
            </div>

            <p className="text-xs text-slate-300 leading-relaxed">
              This message is scheduled to be delivered on{' '}
              <strong>{formatScheduledDisplay(cancellingItem.scheduled_at_utc, cancellingItem.timezone)}</strong> ({cancellingItem.timezone}).
            </p>

            {cancelError && (
              <div className="p-2.5 bg-red-500/10 border border-red-500/20 rounded-lg text-xs text-red-300 leading-tight">
                {cancelError}
              </div>
            )}

            <div className="flex items-center justify-end space-x-2 pt-2 border-t border-slate-800">
              <button
                type="button"
                onClick={() => setCancellingItem(null)}
                disabled={cancellingLoading}
                className="px-3.5 py-2 rounded-xl border border-slate-800 hover:bg-slate-800 text-xs font-medium text-slate-300"
              >
                Keep Scheduled
              </button>
              <button
                type="button"
                onClick={handleConfirmCancel}
                disabled={cancellingLoading}
                className="px-4 py-2 rounded-xl bg-red-500 hover:bg-red-600 text-white text-xs font-semibold shadow-md shadow-red-500/20 flex items-center gap-1.5 disabled:opacity-50"
              >
                {cancellingLoading ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    <span>Cancelling...</span>
                  </>
                ) : (
                  <span>Cancel Message</span>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
