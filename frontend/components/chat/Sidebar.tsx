'use client';

import React, { useState, useEffect, useRef } from 'react';
import { api } from '@/services/api';
import { useAuth } from '@/components/auth/AuthProvider';
import { Conversation, User } from '@/types';
import { Search, LogOut, MessageSquare, Clock, Loader2, Sparkles, UserPlus, X } from 'lucide-react';

interface SidebarProps {
  conversations: Conversation[];
  selectedConversationId: string | null;
  onSelectConversation: (conversation: Conversation) => void;
  onConversationCreated: (conversation: Conversation) => void;
  isOpenMobile?: boolean;
  onCloseMobile?: () => void;
}

export default function Sidebar({
  conversations,
  selectedConversationId,
  onSelectConversation,
  onConversationCreated,
  isOpenMobile = false,
  onCloseMobile,
}: SidebarProps) {
  const { user, logout } = useAuth();
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<User[]>([]);
  const [searching, setSearching] = useState(false);
  const searchTimeoutRef = useRef<any>(null);

  // Search Debounce
  useEffect(() => {
    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current);
    }

    if (!searchQuery.trim()) {
      setSearchResults([]);
      setSearching(false);
      return;
    }

    setSearching(true);
    searchTimeoutRef.current = setTimeout(async () => {
      try {
        const users = await api.searchUsers(searchQuery.trim());
        // Filter out self from search results
        setSearchResults(users.filter((u) => u.id !== user?.id));
      } catch (err) {
        console.error('Failed to search users:', err);
      } finally {
        setSearching(false);
      }
    }, 350);

    return () => {
      if (searchTimeoutRef.current) {
        clearTimeout(searchTimeoutRef.current);
      }
    };
  }, [searchQuery, user]);

  const handleStartChat = async (recipient: User) => {
    try {
      const conv = await api.createConversation(recipient.id);
      onConversationCreated(conv);
      setSearchQuery('');
      setSearchResults([]);
      if (onCloseMobile) {
        onCloseMobile();
      }
    } catch (err) {
      console.error('Failed to start conversation:', err);
    }
  };

  const getOtherParticipant = (conv: Conversation) => {
    if (!user) return null;
    const participant = conv.participants.find((p) => p.user_id !== user.id);
    return participant?.user || null;
  };

  const renderAvatar = (u: User | null, isSelected: boolean = false) => {
    if (!u) return null;
    if (u.avatar_url) {
      return (
        <img
          src={u.avatar_url}
          alt={u.display_name}
          className="w-10 h-10 rounded-full object-cover border border-slate-800 shrink-0"
        />
      );
    }

    const initial = (u.display_name || u.username || '?').charAt(0).toUpperCase();
    return (
      <div
        className={`w-10 h-10 rounded-full flex items-center justify-center font-bold text-xs shrink-0 transition-colors ${
          isSelected
            ? 'bg-brand-500 text-white shadow-md shadow-brand-500/25'
            : 'bg-brand-500/10 border border-brand-500/20 text-brand-400'
        }`}
      >
        {initial}
      </div>
    );
  };

  return (
    <div
      className={`w-80 h-screen flex flex-col bg-slate-900 border-r border-slate-800 text-slate-100 shrink-0 transition-transform duration-200 z-30 ${
        isOpenMobile ? 'fixed inset-y-0 left-0 max-w-[85vw] shadow-2xl' : 'hidden md:flex'
      }`}
    >
      {/* Brand Header */}
      <div className="p-4 border-b border-slate-800 bg-slate-950/40 flex items-center justify-between shrink-0">
        <div className="flex items-center space-x-2.5">
          <div className="w-8 h-8 bg-gradient-to-tr from-brand-600 to-brand-500 rounded-xl flex items-center justify-center shadow-lg shadow-brand-500/20 relative">
            <MessageSquare className="w-4 h-4 text-white" />
            <div className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 bg-amber-400 rounded-full border-2 border-slate-900" />
          </div>
          <div>
            <span className="font-extrabold text-base tracking-tight text-white block">
              LATEXT
            </span>
          </div>
        </div>

        <div className="flex items-center space-x-1">
          <div className="flex items-center space-x-1 bg-brand-500/10 border border-brand-500/20 text-brand-300 rounded-full px-2.5 py-0.5 text-[10px] font-semibold">
            <Sparkles className="w-2.5 h-2.5 text-amber-400" />
            <span>v1.0</span>
          </div>
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

      {/* User Search Input */}
      <div className="p-3 relative z-20 shrink-0">
        <div className="relative">
          <Search className="absolute left-3 top-2.5 w-4 h-4 text-slate-500" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search users to start chat..."
            className="w-full bg-slate-950 border border-slate-800 focus:border-brand-500 focus:ring-1 focus:ring-brand-500/50 text-white rounded-xl pl-9 pr-8 py-2 text-xs transition-colors outline-none"
          />
          {searching && (
            <Loader2 className="absolute right-3 top-2.5 w-4 h-4 text-slate-500 animate-spin" />
          )}
        </div>

        {/* Search Results Dropdown */}
        {searchResults.length > 0 && (
          <div className="absolute left-3 right-3 mt-1.5 bg-slate-950 border border-slate-800 rounded-xl shadow-2xl overflow-hidden max-h-60 overflow-y-auto z-50 divide-y divide-slate-850">
            {searchResults.map((u) => (
              <button
                key={u.id}
                onClick={() => handleStartChat(u)}
                className="w-full px-3 py-2.5 flex items-center space-x-3 hover:bg-slate-900 text-left transition-colors group"
              >
                {renderAvatar(u)}
                <div className="min-w-0 flex-1">
                  <div className="text-xs font-semibold text-white group-hover:text-brand-300 truncate">
                    {u.display_name}
                  </div>
                  <div className="text-[10px] text-slate-400 truncate">@{u.username}</div>
                </div>
                <UserPlus className="w-4 h-4 text-slate-500 group-hover:text-brand-400 shrink-0" />
              </button>
            ))}
          </div>
        )}

        {searchQuery && !searching && searchResults.length === 0 && (
          <div className="absolute left-3 right-3 mt-1.5 bg-slate-950 border border-slate-800 rounded-xl shadow-2xl p-3 text-center text-xs text-slate-500 z-50">
            No users found matching "{searchQuery}"
          </div>
        )}
      </div>

      {/* Conversations List */}
      <div className="flex-1 overflow-y-auto px-2 space-y-1">
        <div className="px-2 py-1 text-[10px] font-bold text-slate-400 uppercase tracking-wider">
          Conversations
        </div>

        {conversations.length === 0 ? (
          <div className="text-center text-xs text-slate-500 py-12 px-4 space-y-2">
            <p className="font-semibold text-slate-300">No active chats</p>
            <p className="text-[11px] text-slate-500 leading-relaxed">
              Use the search bar above to find a teammate and start a conversation.
            </p>
          </div>
        ) : (
          conversations.map((conv) => {
            const otherUser = getOtherParticipant(conv);
            if (!otherUser) return null;
            const isSelected = conv.id === selectedConversationId;

            return (
              <button
                key={conv.id}
                onClick={() => {
                  onSelectConversation(conv);
                  if (onCloseMobile) {
                    onCloseMobile();
                  }
                }}
                className={`w-full p-2.5 flex items-center space-x-3 rounded-xl text-left transition-all ${
                  isSelected
                    ? 'bg-brand-500/15 border border-brand-500/30 text-white shadow-sm'
                    : 'hover:bg-slate-800/80 text-slate-300 border border-transparent'
                }`}
              >
                {renderAvatar(otherUser, isSelected)}
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-bold text-white truncate">
                    {otherUser.display_name}
                  </div>
                  <div className="text-[10px] text-slate-400 truncate mt-0.5">
                    @{otherUser.username}
                  </div>
                </div>
              </button>
            );
          })
        )}
      </div>

      {/* User Footer Profile */}
      {user && (
        <div className="p-3 border-t border-slate-800 bg-slate-950/80 flex items-center justify-between shrink-0">
          <div className="flex items-center space-x-2.5 min-w-0">
            {renderAvatar(user)}
            <div className="min-w-0">
              <div className="text-xs font-bold text-white truncate">
                {user.display_name}
              </div>
              <div className="text-[10px] text-slate-400 truncate">
                @{user.username}
              </div>
            </div>
          </div>
          <button
            onClick={logout}
            title="Sign Out"
            className="p-2 hover:bg-slate-800 rounded-xl text-slate-400 hover:text-red-400 transition-colors"
            aria-label="Sign Out"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      )}
    </div>
  );
}
