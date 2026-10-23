# Messaging Clyde from Signal or iMessage

*Written 2026-10-22, updated 2026-10-23. Signal and iMessage are proposed, not built. A Discord bridge was built on a branch and not kept; see its section.*

The idea, as in [hermes-agent](https://github.com/NousResearch/hermes-agent)'s gateway: message Clyde from your phone and get its answers back, with the session running on your Mac. Telegram is left out on purpose: bot chats there are not end-to-end encrypted, and it would make Clyde depend on a hosted service. Discord has the same two drawbacks.

## Shape

One `clyde gateway` process with an adapter per platform. Each adapter only translates: a message in becomes a prompt in a Bonnie session over Bonnie's local API (`127.0.0.1`), and Bonnie's replies, permission questions and finished turns go back as messages. Sessions, steering, stopping, permission prompts and automations already exist in Bonnie, so the gateway adds no second agent runtime.

## Security, before anything else

Whoever can message the gateway can run tools on the Mac. So:

- Only allowlisted senders (phone numbers / Apple IDs) are answered; anything else is dropped without a reply.
- Sessions start in `hold`: every permission question goes to the phone as a question, and only an explicit yes from an allowlisted sender approves it. Nothing is approved by default, and `all_in` cannot be turned on from a message.
- Messages leave the machine through the platform, so EGRESS.md gets a row before the feature ships.
- `/doctor` lists the gateway, its allowlist and its adapters.

## Signal

- **How:** Signal has no bot API. [signal-cli](https://github.com/AsamK/signal-cli) (GPL-3.0, Java) runs as a separate process, linked as a secondary device of a Signal account (`signal-cli link`, then scan the code on the phone), in JSON-RPC daemon mode. The adapter reads incoming messages and calls `send` over that JSON-RPC socket. Running it as a separate program keeps its GPL licence apart from Clyde's code.
- **Account:** a separate number for Clyde is cleaner than linking your own: everything sent to that number reaches Clyde.
- **Privacy:** end-to-end encrypted to the Mac. The best of the options.
- **Upkeep:** signal-cli needs a recent Java and has to stay current, because Signal stops accepting old clients after a few months. Clyde would pin a version, check it in `/doctor`, and update it the way it updates oMLX. The linked device also has to stay linked: it drops if the phone removes it or after long inactivity.

## Discord: built, not kept

A bridge was built on a branch: a bot talked to only in direct messages, from an allowlist of Discord user IDs, receiving over Discord's Gateway (a WebSocket, with the `websockets` dependency) and sending over its REST API. It was not kept: Discord can read every message, prompts and code included, and it is a hosted service, against Clyde's "works offline, no hosted-only dependencies" rule.

One part of it stayed: answering a permission question in plain words. A model reads only the reply, and only a plain yes runs the action; anything else holds it and goes to Clyde as instructions. That now works at the terminal's permission prompt and in Bonnie (see [usage.md](usage.md#answering-in-your-own-words)).

## iMessage

- **How:** Apple offers no API. On a Mac only: send by scripting Messages.app (`osascript`, `tell application "Messages" to send … to buddy …`), and read new messages by polling `~/Library/Messages/chat.db` (SQLite: `message`, `handle`, `chat`, `chat_message_join`) for rows past the last one seen.
- **Permissions:** reading `chat.db` needs Full Disk Access for the process running Clyde; sending needs Automation access to Messages. macOS asks for each once.
- **Account:** it runs as your own Apple ID, so Clyde sees every conversation in Messages; the allowlist filters what it acts on, but the access is wide.
- **Upkeep, constantly:** this is the fragile one and needs maintenance on every macOS release.
  - `chat.db`'s schema is private and changes between macOS versions; since macOS 13 the text of many messages is only in the `attributedBody` blob (a serialized `NSAttributedString`), not the `text` column, so a decoder has to follow Apple's format.
  - AppleScript support in Messages is unmaintained by Apple and has broken and returned across releases.
  - Every macOS update needs a check: read, send, reactions, attachments, group chats. CI can't do this (no Messages on GitHub's runners), so it is a manual test on a real Mac.

## Order

Signal first: it is the cleaner integration and encrypted. iMessage only if it's worth owning the per-release upkeep; it should be marked experimental and check the macOS version it was last verified on, refusing to start on a newer one until someone has tested it.
