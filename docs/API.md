# API Reference

The current application is session-based and server-rendered. Important HTTP endpoints include:

| Route | Purpose |
| --- | --- |
| `/login` | Starts password and OTP authentication |
| `/register` | Creates an unapproved user |
| `/verify/<token>` | Verifies a registration email |
| `/forgot-password` | Starts password reset |
| `/reset-password/<token>` | Completes password reset |
| `/chat` | Authenticated chat workspace |
| `/upload` | Authenticated file upload |
| `/admin` | Administrator workspace |

Socket.IO supports authenticated messaging, room membership, typing events, reactions, and direct-message events. These contracts should be captured by automated tests before API versioning or frontend replacement.
