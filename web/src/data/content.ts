export const features = [
  { id: 'topics', category: 'Conversations', title: 'Every idea, in its own place.', description: 'Identifies messages on the same topic, even when multiple discussions unfold at once in one channel.', detail: 'Context and reply links help ideas find their way back to the right conversation.', icon: 'messages', example: 'new-website' },
  { id: 'context', category: 'Conversations', title: 'Keep the flow, keep the context.', description: 'Resumes existing topics when conversations return, rather than starting a fragmented branch from scratch.', detail: 'A topic can be active, dormant, resumed, or closed.', icon: 'sprout', example: 'a-little-garden' },
  { id: 'summary', category: 'Summaries', title: 'Catch up in a few lines.', description: 'A clear summary helps you quickly read what matters after stepping away from the keyboard.', detail: 'Review key highlights, agreed decisions, and open questions; cross-reference with chat whenever needed.', icon: 'sparkles', example: 'new-website' },
  { id: 'threads', category: 'Conversations', title: 'Conversations have a place to stay.', description: 'Organizes discussions into dedicated threads so community members can easily follow along.', detail: 'Discord bot thread actions link back to source messages without altering the original chat.', icon: 'hash', example: 'weekend-project' },
  { id: 'channels', category: 'Control', title: 'Listens only where invited.', description: 'Ingests messages only from enabled servers and channels authorized by administrators.', detail: 'Private spaces stay private. Administrators can pause ingestion per server at any time.', icon: 'shield', example: null },
  { id: 'retention', category: 'Control', title: 'Intentional data retention.', description: 'Message retention duration chosen by administrators to match community policies.', detail: 'Expired data is pruned based on storage configurations. Learn more on our privacy page.', icon: 'leaf', example: null },
];

export const faqs = [
  { category: 'Getting Started', question: 'What does Coconerd do for my server?', answer: 'Coconerd groups related messages into topics, keeps conversational context flowing, and creates concise summaries so everyone can stay in sync. You can explore a live simulation right here on our website.' },
  { category: 'Getting Started', question: 'Do I need an account to use the website?', answer: 'No. You can explore features, read the guide, and test the interactive demo right away without logging in. Data in the demo is self-contained and does not connect to your Discord account.' },
  { category: 'Getting Started', question: 'How do I add Coconerd to Discord?', answer: 'Click "Add to Discord" to check for official invite availability. While the official invite link is being prepared, you can explore how it works using the interactive demo.' },
  { category: 'Conversations', question: 'Are original messages moved or deleted?', answer: 'Conversational organization preserves original messages in their source channel. The Discord bot creates dedicated threads and posts linked copies so members can continue following along.' },
  { category: 'Conversations', question: 'Why does a message not have a topic assigned yet?', answer: 'Messages are received first and classified asynchronously. Very short messages or those lacking context may wait for follow-up chat; not every message forms a topic.' },
  { category: 'Conversations', question: 'What happens when a topic is closed?', answer: 'Closed topics no longer accept new messages. Subsequent discussions are evaluated in their own new context. You can try closing a topic in the interactive demo and reset the demo anytime.' },
  { category: 'Summaries', question: 'Does a summary replace reading original messages?', answer: 'Summaries help you catch up quickly on main points, but AI can occasionally miss subtle nuances. For important decisions, always verify against the original messages.' },
  { category: 'Privacy', question: 'Does Coconerd read all channels?', answer: 'No. The ingestion pipeline only accepts messages from enabled servers and authorized channels. Administrators are in full control of choosing this scope.' },
  { category: 'Privacy', question: 'Is conversation content processed by AI?', answer: 'Yes. When live AI models are enabled, selected message content and context are sent to the configured AI provider. Administrators should notify members and avoid selecting sensitive channels.' },
  { category: 'Privacy', question: 'Do actions in the interactive demo affect Discord?', answer: 'No. All servers, channels, messages, and summaries in the demo workspace are simulated demo data. Changes are stored locally in your browser, and the "Reset Demo" button lets you start fresh anytime.' },
];

export function matchesText(text: string, query: string) {
  const normalize = (value: string) => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  return normalize(text).includes(normalize(query.trim()));
}
