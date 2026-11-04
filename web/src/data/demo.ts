import type { Guild, Message, ModelConfig, Summary, Topic } from '../types';

export const demoGuilds: Guild[] = [
  { guild_id: 'garden', name: 'Coconerd Garden', enabled: true, allowed_channel_ids: ['general', 'product', 'creative'], retention_days: 365 },
  { guild_id: 'studio', name: 'The Little Studio', enabled: true, allowed_channel_ids: ['ideas', 'design'], retention_days: 90 },
];
const now = Date.now();
const ago = (minutes: number) => new Date(now - minutes * 60_000).toISOString();
export const demoTopics: Topic[] = [
  { topic_id: 'a-little-garden', guild_id: 'garden', title: 'A Little Community Garden', description: 'Creating a welcoming space where ideas can grow freely. First steps for the server and new member onboarding.', status: 'ACTIVE', last_activity: ago(4), discord_thread_id: null, message_count: 8 },
  { topic_id: 'weekend-playlist', guild_id: 'garden', title: 'Slow Weekend Playlist', description: 'Soothing background tunes for deep work, reading books, or simply relaxing.', status: 'ACTIVE', last_activity: ago(18), discord_thread_id: null, message_count: 6 },
  { topic_id: 'new-website', guild_id: 'garden', title: 'Idea Corner: Our New Website', description: 'Nature moodboard, earthy colors, and interactive touches for Coconerd\'s new home.', status: 'RESUMED', last_activity: ago(42), discord_thread_id: null, message_count: 5 },
  { topic_id: 'weekend-project', guild_id: 'garden', title: 'Weekend Hackathon — Who is in?', description: 'A nimble tool, a small crew, and two days of focused building. Let\'s make something truly useful.', status: 'ACTIVE', last_activity: ago(120), discord_thread_id: null, message_count: 5 },
  { topic_id: 'book-corner', guild_id: 'garden', title: 'What Book Are You Reading?', description: 'Sharing memorable chapters and lasting takeaways after turning the final page.', status: 'DORMANT', last_activity: ago(1440), discord_thread_id: null, message_count: 4 },
  { topic_id: 'welcome', guild_id: 'garden', title: 'Greetings from New Friends', description: 'A warm round of quick introductions to get to know everyone better.', status: 'CLOSED', last_activity: ago(2880), discord_thread_id: null, message_count: 4 },
  { topic_id: 'studio-design', guild_id: 'studio', title: 'Designing with Simplicity', description: 'Exploring layout balance, tactile textures, and intentional negative space.', status: 'ACTIVE', last_activity: ago(15), discord_thread_id: null, message_count: 4 },
];

const conversations: Record<string, [string, string][]> = {
  'a-little-garden': [['Linh', 'I want our server to feel like a cozy corner where anyone can share ideas without hesitation 🌱'], ['Minh', 'Love that! How about a main lounge plus dedicated channels for small projects?'], ['An', 'Messages fly by so quickly — is there a good way to keep track of key discussions?'], ['Linh', 'Coconerd groups related messages into topics and writes a digest so newcomers can catch up easily.'], ['Huy', 'That means we don\'t have to manually create threads for every single topic.'], ['Minh', 'Let\'s start with #general, #product, and #creative!'], ['An', 'Agreed. I\'ll draft a welcome note for new members this weekend.'], ['Linh', 'All set. A little garden growing from great conversations ✨']],
  'weekend-playlist': [['An', 'Anyone got a gentle ambient playlist for deep work?'], ['Huy', 'I usually listen to soft rain and minimalist piano.'], ['Linh', 'Add a touch of acoustic guitar and it\'s perfect 🌙'], ['Minh', 'Here\'s some slow jazz to round it out.'], ['An', 'I\'ll compile these into a shared playlist!'], ['Huy', 'Let\'s name it "Slow Weekend Chill"!']],
};
export function demoMessages(topic: Topic): Message[] {
  const entries = conversations[topic.topic_id] || [['Linh', topic.description], ['Minh', 'I love this idea. Let\'s map out the next steps together.'], ['An', 'I\'ll put together a draft for the team to review.'], ['Huy', 'Let\'s sync up more over the weekend 🌿']];
  return entries.map(([author, content], index) => ({ message_id: `${topic.topic_id}-${index}`, channel_id: 'general', author_id: author, author_name: author, content, created_at: ago((entries.length - index) * 8) })).reverse();
}
export function demoSummary(topic: Topic): Summary {
  return { version: 2, source_message_ids: demoMessages(topic).map(m => m.message_id), summary: topic.description, key_points: topic.topic_id === 'a-little-garden' ? ['Create a welcoming, approachable space for sharing ideas.', 'Launch with three channels: #general, #product, and #creative.', 'Use Coconerd to organize topics and help new members catch up effortlessly.'] : ['The team is exchanging thoughts and collecting feedback.', 'Preparing an initial draft ahead of the upcoming discussion.'], open_questions: ['Which ideas should be prioritized for next week?'] };
}
export const defaultModel: ModelConfig = { provider: 'meta', model_id: 'muse-spark-1.3', temperature: 0, max_tokens: 2048 };
