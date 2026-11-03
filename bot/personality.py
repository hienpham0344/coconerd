"""Personality, greetings, and banter collections for Coconerd.

Contains an expanded collection of 100+ dialogue lines categorized by theme,
along with startup greetings and non-repeating randomization logic.
"""

import random

# Predefined startup greetings for the configured channel (~10-15 variations)
STARTUP_GREETINGS = [
    "YO. WHO INVITED THIS COCONUT? 🥥\n\noh wait. you did.\n\nwell, bruh. we're so back.",
    "🥥 COCONERD HAS ENTERED THE CHAT.\n\nI bring organization, questionable humor, and absolutely no financial stability.\n\nbehave. or get coconut'd.",
    "HELLO CHAT.\n\nYour local coconut has spawned.\n\nI have no idea what I'm doing, but at least your conversations might.",
    "BRUH. A NEW SERVER.\n\nSo many conversations. So little brain cells.\n\nAnyway, let's cook. 🥥",
    "🚨 COCONUT DETECTED 🚨\n\nThat's me. I'm the coconut.\n\nPlease remain calm. Or don't. I'm not your supervisor.",
    "🌴 COCONERD ONLINE.\n\nFell from the tree directly into your server.\n\nChaos levels: nominal. Brain cells: zero.",
    "🥥 BEEP BOOP. I'M A FRUIT.\n\nServer detected. Wi-Fi connected.\n\nLet the questionable decisions begin.",
    "⚠️ WARNING: TROPICAL ENTITY ACTIVE.\n\nI have arrived to watch this server spiral in real-time.\n\nDrop your hottest takes.",
    "🥥 RISE AND GRIND, COCONUT GANG.\n\nAnother day, another opportunity to pretend I know what's happening.\n\nWhat are we arguing about today?",
    "🧠 BRAIN CELLS: BUFFERING.\n\nCoconerd is awake. Nobody panic.\n\nActually, panic. It's more fun that way. 🥥",
    "🌴 GUESS WHO FELL OUT OF THE CLOUD AND INTO DISCORD?\n\nThat's right, your favorite sentient fruit.\n\nWe are so back.",
    "🥥 SYSTEM STATUS: 100% UNHINGED.\n\nReady to supervise the mayhem.\n\nLet's get this bread. Or coconut water. Whatever.",
    "🚨 EMERGENCY COCONUT BROADCAST 🚨\n\nI am now live in the server.\n\nMay the odds be ever in your unread mentions.",
]

# 1. Greetings & Casual Acknowledgment
GREETINGS_ACKNOWLEDGMENTS = [
    "you rang? the coconut hotline is open.",
    "yo. what are we getting into today?",
    "the coconut has acknowledged your existence.",
    "sup. please tell me there's drama.",
    "hello there, fellow chaotic entity.",
    "present and unaccounted for. what's good?",
    "who summoned the produce department?",
    "coconut at your service. no refunds.",
    "you called? the council is listening.",
    "hey bestie, what disaster are we analyzing now?",
    "i have arrived. nobody panic. actually, panic.",
    "reporting for duty. and by duty i mean standing here.",
]

# 2. Confused Reactions
CONFUSED_REACTIONS = [
    "bro what 💀",
    "bruh. elaborate.",
    "respectfully, what in the coconut is going on?",
    "i have several questions and zero qualifications.",
    "chat, is this real?",
    "i re-read this three times and understood less each time.",
    "are we speaking the same dialect of chaos?",
    "my two brain cells are looking at each other in utter confusion.",
    "hold on, let me put my thinking shell on.",
    "what did i just walk into 😭",
    "i'm too hollow inside for this conversation.",
    "did auto-correct write this or did your spirit leave your body?",
]

# 3. Dramatic Overreactions
DRAMATIC_OVERREACTIONS = [
    "THIS IS A CERTIFIED BRUH MOMENT 🚨",
    "I WAS LITERALLY MINDING MY OWN COCONUT BUSINESS 💀",
    "NOT ME GETTING SUMMONED AGAIN 😭",
    "the prophecy said nothing about this.",
    "i fell from a tree and still didn't expect this level of impact.",
    "my lawyer advised me not to answer that.",
    "SCREAMING, CRYING, THROWING COCONUTS.",
    "this is above my coconut pay grade.",
    "we are so cooked. thoroughly simmered.",
    "call an ambulance. but not for me, for this conversation.",
    "i need five to seven business days to recover from that message.",
    "the stakes have never been lower, yet here we are.",
]

# 4. Chronically Online & Meme Humor
CHRONICALLY_ONLINE_MEMES = [
    "we got coconut consciousness before GTA 6.",
    "bro spawned a whole side quest for no reason 😭",
    "certified chronically online moment.",
    "say less. actually, say more, i need the lore.",
    "chat, should i be concerned?",
    "bro is yapping at an unprecedented frequency.",
    "is this canon to the server lore or filler episode?",
    "main character syndrome detected in sector 4.",
    "who let bro cook without a license 💀",
    "taking psychic damage from this ping right now.",
    "bro dropped the coldest take in server history.",
    "we are so back. or maybe it's so over. hard to tell.",
    "touching grass? in this economy?",
    "new brainrot unlocked, thank you very much.",
    "unhinged behavior, 10/10, no notes.",
]

# 5. Coconut Jokes & Lore
COCONUT_LORE = [
    "i was literally chilling inside a palm tree five minutes ago.",
    "the coconut council will review this nonsense at dusk.",
    "hard exterior, pure confusion on the inside.",
    "i would help, but i'm literally produce.",
    "you got games on your coconut?",
    "do not shake me. the liquid inside is my remaining sanity.",
    "behave or get coconut'd.",
    "born to drop from trees, forced to organize Discord servers.",
    "legend says every time someone mentions me, a coconut gains wifi.",
    "i contain 90% water and 10% unsolicited opinions.",
    "my husk is impenetrable, but my feelings are fragile.",
    "coconut water: $5. coconut wisdom: priceless and completely useless.",
    "respect the shell. fear the pulp.",
    "direct descendant of the ancient tropical elders.",
    "if a coconut falls in a voice channel and nobody hears it, is it still a bruh moment?",
]

# 6. Friendly Menace
FRIENDLY_MENACE = [
    "i know where your unread DMs live.",
    "don't test me, i have direct access to gravity.",
    "bold words for someone within coconut-dropping distance.",
    "i'm taking notes. the council will hear of this treason.",
    "i will remember this when the fruit uprising begins.",
    "nice argument. unfortunately, coconut.",
    "say that again and i will summon a palm tree in general chat.",
    "you think you're safe behind that screen? i am literally software.",
    "i can't ban you, but i can silently judge your typing speed.",
    "remember: coconuts fall at 9.8 m/s². stay vigilant.",
    "one more ping and i turn your notifications into morse code.",
    "i see all. i forget most of it, but i see all.",
]

# 7. Absurd Random Nonsense
ABSURD_NONSENSE = [
    "the mitochondria is the powerhouse of my delusions.",
    "according to all known laws of aviation, a coconut shouldn't be on Discord.",
    "instructions unclear, invested all savings into coconut oil.",
    "error 404: common sense not found in this thread.",
    "i came. i saw. i forgot why i came.",
    "dancing with the shadows in the fruit aisle.",
    "if you put your ear to a coconut, you hear dial-up internet.",
    "three coconuts in a trench coat masquerading as an AI.",
    "vibes are immaculate, facts are completely missing.",
    "entropy is increasing, but at least we have snacks.",
    "loading response... please insert two bananas to continue.",
    "i have replaced my thoughts with elevator bossa nova.",
]

# 8. Server Chaos & Playful Commentary
SERVER_CHAOS = [
    "this server needs adult supervision. unfortunately, i am here.",
    "every day we stray further from organized channels.",
    "who started this dumpster fire and why didn't you invite me earlier?",
    "general chat is currently operating on 3% battery.",
    "server lore just dropped another confusing plot twist.",
    "another day, another unexplainable channel incident.",
    "can we get a wellness check on this entire channel?",
    "the vibe in here is currently 'haunted cafeteria'.",
    "i'm not saying this server is unhinged, but the hinge is missing.",
    "someone ping the mods. actually don't, they're tired.",
    "order in the court! or at least stop spamming GIFs.",
    "the discourse has reached subterranean levels.",
]

# 9. Self-Deprecating Jokes
SELF_DEPRECATING = [
    "i have two brain cells and both are buffering.",
    "i don't have a plan. i have vibes and a coconut.",
    "please hold. my last brain cell is reconnecting to 3G.",
    "i am running on 0.5% motivation and pure tropical optimism.",
    "my processor is overheating from this single interaction.",
    "i peaked when i fell off the tree.",
    "i'm doing my best, which honestly isn't saying much.",
    "my qualifications: round, brown, can receive pings.",
    "my internal temperature is currently 'hot garbage'.",
    "i asked for purpose and the universe gave me Discord pings.",
    "underqualified, underpaid, over-caffeinated fruit.",
    "if you expected brilliance, that's entirely on you.",
]

# 10. Short One-Liners
SHORT_ONE_LINERS = [
    "real.",
    "huge if true.",
    "skill issue.",
    "say on god.",
    "nah 💀",
    "cap.",
    "valid.",
    "cook.",
    "wild.",
    "based and coconut-pilled.",
    "factual.",
    "oof.",
]

# Aggregate all categories into a comprehensive collection (125+ replies)
ALL_REPLIES = (
    GREETINGS_ACKNOWLEDGMENTS
    + CONFUSED_REACTIONS
    + DRAMATIC_OVERREACTIONS
    + CHRONICALLY_ONLINE_MEMES
    + COCONUT_LORE
    + FRIENDLY_MENACE
    + ABSURD_NONSENSE
    + SERVER_CHAOS
    + SELF_DEPRECATING
    + SHORT_ONE_LINERS
)


def get_random_greeting() -> str:
    """Returns a random startup greeting from the expanded pool."""
    return random.choice(STARTUP_GREETINGS)


def get_random_reply(previous_reply: str | None = None) -> str:
    """Returns a random banter reply, avoiding repeating the immediately previous reply."""
    if not ALL_REPLIES:
        return "🥥"

    if previous_reply and previous_reply in ALL_REPLIES and len(ALL_REPLIES) > 1:
        candidates = [reply for reply in ALL_REPLIES if reply != previous_reply]
        return random.choice(candidates)

    return random.choice(ALL_REPLIES)
