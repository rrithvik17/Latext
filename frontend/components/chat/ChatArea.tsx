'use client';

import React, { useState, useEffect, useRef } from 'react';
import { useAuth } from '@/components/auth/AuthProvider';
import { Conversation, Message, User } from '@/types';
import { Send, Check, CheckCheck, Loader2, Clock, Calendar, ChevronLeft, Wifi, WifiOff } from 'lucide-react';
import { ScheduleDialog } from './ScheduleDialog';
import { api } from '../../services/api';

interface ChatAreaProps {
  conversation: Conversation;
  messages: Message[];
  wsStatus: 'CONNECTING' | 'OPEN' | 'CLOSED';
  onSendMessage: (content: string) => void;
  sendWsEvent: (event: string, data: any) => boolean;
  onScheduledMessageCreated?: () => void;
  onBackMobile?: () => void;
  onToggleScheduledMobile?: () => void;
}

export default function ChatArea({
  conversation,
  messages,
  wsStatus,
  onSendMessage,
  sendWsEvent,
  onScheduledMessageCreated,
  onBackMobile,
  onToggleScheduledMobile,
}: ChatAreaProps) {
  const { user } = useAuth();
  const [inputText, setInputText] = useState('');
  const [isScheduleOpen, setIsScheduleOpen] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  const otherParticipant = conversation.participants.find((p) => p.user_id !== user?.id)?.user || null;

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Automatically mark incoming messages as READ when this chat is open
  useEffect(() => {
    if (wsStatus !== 'OPEN' || !user || messages.length === 0) return;

    // Find messages from the other user that are not yet READ
    const unreadIds = messages
      .filter((m) => m.sender_id !== user.id && m.status !== 'READ')
      .map((m) => m.id);

    if (unreadIds.length > 0) {
      sendWsEvent('read', { message_ids: unreadIds });
    }
  }, [messages, user, wsStatus, sendWsEvent]);

  const handleSend = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputText.trim()) return;

    onSendMessage(inputText.trim());
    setInputText('');
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend(e);
    }
  };

  const handleConfirmSchedule = async (scheduledAt: string, timezone: string) => {
    await api.createScheduledMessage({
      conversation_id: conversation.id,
      content: inputText.trim(),
      scheduled_at: scheduledAt,
      timezone: timezone,
    });
    setInputText('');
    setIsScheduleOpen(false);
    if (onScheduledMessageCreated) {
      onScheduledMessageCreated();
    }
  };

  const renderDeliveryStatus = (msg: Message) => {
    if (msg.sender_id !== user?.id) return null;

    if (msg.status === 'READ') {
      return (
        <span title="Read by recipient" className="flex items-center text-brand-200">
          <CheckCheck className="w-3.5 h-3.5" />
        </span>
      );
    } else if (msg.status === 'DELIVERED') {
      return (
        <span title="Delivered to recipient" className="flex items-center text-brand-200/70">
          <CheckCheck className="w-3.5 h-3.5" />
        </span>
      );
    } else {
      return (
        <span title="Sent to server" className="flex items-center text-brand-200/70">
          <Check className="w-3.5 h-3.5" />
        </span>
      );
    }
  };

  const formatMessageTime = (isoString: string) => {
    try {
      const d = new Date(isoString);
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return '';
    }
  };

  const getMessageDateHeader = (isoString: string) => {
    try {
      const msgDate = new Date(isoString);
      const today = new Date();
      const yesterday = new Date();
      yesterday.setDate(today.getDate() - 1);

      if (msgDate.toDateString() === today.toDateString()) {
        return 'Today';
      } else if (msgDate.toDateString() === yesterday.toDateString()) {
        return 'Yesterday';
      }
      return msgDate.toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        year: msgDate.getFullYear() !== today.getFullYear() ? 'numeric' : undefined,
      });
    } catch {
      return '';
    }
  };

  return (
    <div className="flex-1 h-screen flex flex-col bg-slate-950 text-slate-100 min-w-0">
      {/* Conversation Header */}
      {otherParticipant && (
        <div className="p-3.5 border-b border-slate-800 bg-slate-900/80 backdrop-blur-sm flex items-center justify-between z-10 shrink-0">
          <div className="flex items-center space-x-3 min-w-0">
            {/* Mobile back button */}
            {onBackMobile && (
              <button
                onClick={onBackMobile}
                className="md:hidden p-1.5 -ml-1 text-slate-400 hover:text-white rounded-lg"
                title="Back to conversations"
              >
                <ChevronLeft className="w-5 h-5" />
              </button>
            )}

            <div className="w-9 h-9 rounded-full bg-brand-500/10 border border-brand-500/20 text-brand-400 flex items-center justify-center font-bold text-xs shrink-0">
              {otherParticipant.display_name.charAt(0).toUpperCase()}
            </div>
            <div className="min-w-0">
              <div className="text-xs font-bold text-white truncate">
                {otherParticipant.display_name}
              </div>
              <div className="text-[10px] text-slate-400 truncate">
                @{otherParticipant.username}
              </div>
            </div>
          </div>

          {/* Right Header Status / Mobile Controls */}
          <div className="flex items-center space-x-2 shrink-0">
            {/* Connection Indicator */}
            {wsStatus === 'OPEN' && (
              <div
                className="flex items-center space-x-1.5 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 rounded-full px-2.5 py-0.5 text-[10px] font-semibold"
                title="Real-time WebSocket connection active"
              >
                <span className="w-1.5 h-1.5 bg-emerald-400 rounded-full animate-pulse" />
                <span className="hidden sm:inline">Connected</span>
              </div>
            )}
            {wsStatus === 'CONNECTING' && (
              <div
                className="flex items-center space-x-1.5 bg-amber-500/10 border border-amber-500/20 text-amber-400 rounded-full px-2.5 py-0.5 text-[10px] font-semibold"
                title="Connecting to WebSocket stream"
              >
                <Loader2 className="w-3 h-3 animate-spin" />
                <span className="hidden sm:inline">Connecting...</span>
              </div>
            )}
            {wsStatus === 'CLOSED' && (
              <div
                className="flex items-center space-x-1.5 bg-amber-500/10 border border-amber-500/20 text-amber-300 rounded-full px-2.5 py-0.5 text-[10px] font-semibold"
                title="Offline — attempting automatic reconnection"
              >
                <WifiOff className="w-3 h-3 text-amber-400" />
                <span>Reconnecting...</span>
              </div>
            )}

            {/* Mobile toggle for Scheduled Queue */}
            {onToggleScheduledMobile && (
              <button
                onClick={onToggleScheduledMobile}
                className="md:hidden p-2 text-slate-400 hover:text-brand-400 rounded-lg hover:bg-slate-800"
                title="Open scheduled queue"
              >
                <Clock className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>
      )}

      {/* Messages Scroll Area */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center p-6 space-y-2 text-slate-500">
            <div className="w-12 h-12 rounded-2xl bg-slate-900 border border-slate-800 flex items-center justify-center mb-1">
              <Clock className="w-6 h-6 text-slate-600" />
            </div>
            <p className="text-xs font-semibold text-slate-300">No messages yet</p>
            <p className="text-[11px] text-slate-500 max-w-xs leading-relaxed">
              Send an instant message or schedule one to be delivered at a specific future time.
            </p>
          </div>
        ) : (
          messages.map((msg, index) => {
            const isMe = msg.sender_id === user?.id;
            const prevMsg = index > 0 ? messages[index - 1] : null;
            const showDateHeader =
              !prevMsg ||
              getMessageDateHeader(msg.created_at) !== getMessageDateHeader(prevMsg.created_at);

            return (
              <React.Fragment key={msg.id}>
                {showDateHeader && (
                  <div className="flex items-center justify-center my-3">
                    <span className="px-2.5 py-0.5 bg-slate-900/90 border border-slate-800 text-slate-400 rounded-full text-[10px] font-semibold tracking-wider uppercase shadow-sm">
                      {getMessageDateHeader(msg.created_at)}
                    </span>
                  </div>
                )}

                <div className={`flex ${isMe ? 'justify-end' : 'justify-start'}`}>
                  <div
                    className={`max-w-[75%] sm:max-w-[65%] rounded-2xl px-4 py-2.5 shadow-md flex flex-col space-y-1 relative ${
                      isMe
                        ? 'bg-brand-500 text-white rounded-tr-none'
                        : 'bg-slate-900 border border-slate-800/90 text-slate-100 rounded-tl-none'
                    }`}
                  >
                    <p className="text-xs break-words leading-relaxed whitespace-pre-wrap">
                      {msg.content}
                    </p>
                    <div className="flex items-center justify-end space-x-1 self-end pt-0.5">
                      <span
                        className={`text-[9px] font-mono ${
                          isMe ? 'text-brand-100' : 'text-slate-500'
                        }`}
                      >
                        {formatMessageTime(msg.created_at)}
                      </span>
                      {renderDeliveryStatus(msg)}
                    </div>
                  </div>
                </div>
              </React.Fragment>
            );
          })
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Message Composer Footer */}
      <div className="p-3 border-t border-slate-800 bg-slate-900/50 backdrop-blur-sm shrink-0">
        <form onSubmit={handleSend} className="flex items-end space-x-2">
          <textarea
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type a message... (Enter to send, Shift+Enter for newline)"
            rows={1}
            className="flex-1 bg-slate-950 border border-slate-800 focus:border-brand-500 focus:ring-1 focus:ring-brand-500/50 text-white rounded-xl px-3.5 py-2 text-xs outline-none resize-none max-h-24 min-h-[38px] transition-colors leading-relaxed"
          />
          <button
            type="button"
            disabled={!inputText.trim()}
            onClick={() => setIsScheduleOpen(true)}
            className="bg-slate-800 hover:bg-slate-700 active:bg-slate-850 text-slate-300 hover:text-white p-2.5 rounded-xl transition-all disabled:opacity-40 disabled:cursor-not-allowed shadow-md flex items-center justify-center h-[38px] w-[38px] shrink-0 group relative"
            title="Schedule for future delivery"
            aria-label="Schedule for future delivery"
          >
            <Clock className="w-4 h-4 group-hover:scale-110 transition-transform" />
          </button>
          <button
            type="submit"
            disabled={!inputText.trim()}
            className="bg-brand-500 hover:bg-brand-600 active:bg-brand-700 text-white p-2.5 rounded-xl transition-all disabled:opacity-40 disabled:cursor-not-allowed shadow-md shadow-brand-500/20 flex items-center justify-center h-[38px] w-[38px] shrink-0"
            title="Send immediately"
            aria-label="Send immediately"
          >
            <Send className="w-4 h-4" />
          </button>
        </form>
      </div>

      <ScheduleDialog
        isOpen={isScheduleOpen}
        onClose={() => setIsScheduleOpen(false)}
        messagePreview={inputText}
        recipient={otherParticipant}
        onConfirm={handleConfirmSchedule}
      />
    </div>
  );
}
