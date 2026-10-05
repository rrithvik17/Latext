export interface User {
  id: string;
  username: string;
  email: string;
  display_name: string;
  avatar_url?: string;
  created_at: string;
  updated_at: string;
  last_seen_at: string;
}

export interface ConversationParticipant {
  conversation_id: string;
  user_id: string;
  joined_at: string;
  user: User;
}

export interface Conversation {
  id: string;
  created_at: string;
  updated_at: string;
  participants: ConversationParticipant[];
}

export interface Message {
  id: string;
  conversation_id: string;
  sender_id: string;
  content: string;
  message_type: string;
  status: 'SENT' | 'DELIVERED' | 'READ';
  created_at: string;
  updated_at: string;
}

export interface ScheduledMessage {
  id: string;
  conversation_id: string;
  sender_id: string;
  content: string;
  message_type: string;
  scheduled_at_utc: string;
  timezone: string;
  status: 'SCHEDULED' | 'PROCESSING' | 'SENT' | 'CANCELLED' | 'FAILED';
  created_at: string;
  updated_at: string;
  sent_at?: string;
  cancelled_at?: string;
  failure_reason?: string;
  attempt_count: number;
}
