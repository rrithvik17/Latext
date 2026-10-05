'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { useAuth } from '@/components/auth/AuthProvider';
import { api } from '@/services/api';
import { Conversation, Message } from '@/types';
import Sidebar from '@/components/chat/Sidebar';
import ChatArea from '@/components/chat/ChatArea';
import EmptyState from '@/components/chat/EmptyState';
import { ScheduledList } from '@/components/chat/ScheduledList';
import { useWebSocket } from '@/hooks/useWebSocket';
import { Loader2 } from 'lucide-react';

export default function DashboardPage() {
  const { user, loading: authLoading } = useAuth();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedConversation, setSelectedConversation] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [loadingConversations, setLoadingConversations] = useState(true);
  const [scheduledRefreshTrigger, setScheduledRefreshTrigger] = useState(0);

  // Responsive Drawer States
  const [sidebarOpenMobile, setSidebarOpenMobile] = useState(false);
  const [scheduledOpenMobile, setScheduledOpenMobile] = useState(false);

  // Fetch initial conversations
  const fetchConversations = async () => {
    try {
      const data = await api.getConversations();
      setConversations(data);
    } catch (err) {
      console.error('Failed to fetch conversations:', err);
    } finally {
      setLoadingConversations(false);
    }
  };

  useEffect(() => {
    if (user) {
      fetchConversations();
    }
  }, [user]);

  // Load historical messages when selection changes
  useEffect(() => {
    if (!selectedConversation) {
      setMessages([]);
      return;
    }

    const loadMessages = async () => {
      try {
        const data = await api.getMessages(selectedConversation.id);
        setMessages(data);
      } catch (err) {
        console.error('Failed to load messages:', err);
      }
    };

    loadMessages();
  }, [selectedConversation]);

  // WebSocket Message Receivers
  const handleMessageReceived = useCallback((newMsg: Message) => {
    setMessages((prev) => {
      if (prev.some((m) => m.id === newMsg.id)) {
        return prev.map((m) => (m.id === newMsg.id ? newMsg : m));
      }
      return [...prev, newMsg];
    });
  }, []);

  const handleStatusUpdate = useCallback((update: { message_id: string; status: string }) => {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === update.message_id ? { ...m, status: update.status as any } : m
      )
    );
  }, []);

  // Hook into WebSocket connection
  const { status: wsStatus, sendEvent } = useWebSocket(
    selectedConversation ? selectedConversation.id : null,
    handleMessageReceived,
    handleStatusUpdate
  );

  // Sync missing history on connection recovery
  useEffect(() => {
    if (selectedConversation && wsStatus === 'OPEN') {
      const syncMessages = async () => {
        try {
          const data = await api.getMessages(selectedConversation.id);
          setMessages(data);
        } catch (err) {
          console.error('Failed to sync messages:', err);
        }
      };
      syncMessages();
    }
  }, [selectedConversation, wsStatus]);

  const handleSendMessage = (content: string) => {
    // Send via WebSocket first
    const sent = sendEvent('message', { content });
    
    // Fallback to REST API if socket connection is closed
    if (!sent && selectedConversation) {
      api.sendMessage(selectedConversation.id, content)
        .then((newMsg) => {
          setMessages((prev) => [...prev, newMsg]);
        })
        .catch((err) => console.error('Failed to send message via fallback REST:', err));
    }
  };

  const handleConversationCreated = (newConv: Conversation) => {
    setConversations((prev) => {
      if (prev.some((c) => c.id === newConv.id)) {
        return prev;
      }
      return [newConv, ...prev];
    });
    setSelectedConversation(newConv);
  };

  const handleScheduledCreated = () => {
    setScheduledRefreshTrigger((prev) => prev + 1);
  };

  const handleSelectConversationById = (conversationId: string) => {
    const conv = conversations.find((c) => c.id === conversationId);
    if (conv) {
      setSelectedConversation(conv);
      setScheduledOpenMobile(false);
    }
  };

  if (authLoading || (user && loadingConversations)) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <div className="flex flex-col items-center space-y-4">
          <Loader2 className="w-9 h-9 text-brand-500 animate-spin" />
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
            Loading Latext...
          </p>
        </div>
      </div>
    );
  }

  if (!user) return null; // AuthProvider handles redirect

  return (
    <div className="h-screen w-screen flex bg-slate-950 overflow-hidden relative">
      {/* Mobile Backdrop Overlay */}
      {(sidebarOpenMobile || scheduledOpenMobile) && (
        <div
          onClick={() => {
            setSidebarOpenMobile(false);
            setScheduledOpenMobile(false);
          }}
          className="fixed inset-0 bg-slate-950/80 backdrop-blur-sm z-20 md:hidden"
        />
      )}

      {/* Sidebar (Conversations & Search) */}
      <Sidebar
        conversations={conversations}
        selectedConversationId={selectedConversation ? selectedConversation.id : null}
        onSelectConversation={(conv) => {
          setSelectedConversation(conv);
          setSidebarOpenMobile(false);
        }}
        onConversationCreated={handleConversationCreated}
        isOpenMobile={sidebarOpenMobile}
        onCloseMobile={() => setSidebarOpenMobile(false)}
      />

      {/* Main Workspace (Chat Area or Welcome State) */}
      <div className="flex-1 flex overflow-hidden min-w-0">
        {selectedConversation ? (
          <ChatArea
            conversation={selectedConversation}
            messages={messages}
            wsStatus={wsStatus}
            onSendMessage={handleSendMessage}
            sendWsEvent={sendEvent}
            onScheduledMessageCreated={handleScheduledCreated}
            onBackMobile={() => setSidebarOpenMobile(true)}
            onToggleScheduledMobile={() => setScheduledOpenMobile(!scheduledOpenMobile)}
          />
        ) : (
          <EmptyState onOpenSidebarMobile={() => setSidebarOpenMobile(true)} />
        )}

        {/* Scheduled Message Queue Sidebar */}
        <ScheduledList
          conversations={conversations}
          currentUserId={user.id}
          onRefreshTrigger={scheduledRefreshTrigger}
          onSelectConversation={handleSelectConversationById}
          isOpenMobile={scheduledOpenMobile}
          onCloseMobile={() => setScheduledOpenMobile(false)}
        />
      </div>
    </div>
  );
}
