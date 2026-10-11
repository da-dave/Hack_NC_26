
/**
 * PantryPulse — Photon Spectrum iMessage Agent
 *
 * Connects real iMessage conversations to the local
 * Python/CSV PantryPulse backend.
 *
 * Run:
 *   npx tsx src/pantrypulse.ts
 */

import "dotenv/config";
import { Spectrum } from "spectrum-ts";
import { imessage } from "spectrum-ts/providers/imessage";

// Local Python backend.
// Change through .env if necessary.
const bridge = (
  process.env.PANTRYPULSE_BRIDGE_URL ||
  "http://127.0.0.1:8765"
).replace(/\/+$/, "");

type OutgoingMessage = {
  id: string;
  recipient: string;
  space_id: string;
  text: string;
};

// Communicate with the Python backend.
async function api(
  path: string,
  body?: Record<string, unknown>
): Promise<any> {
  const options: RequestInit | undefined = body
    ? {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    }
    : undefined;

  const response = await fetch(bridge + path, {
    ...options,
    signal: AbortSignal.timeout(15000),
  });
  const data = await response.json();

  if (!response.ok) {
    throw new Error(
      `Python backend ${path}: ` +
      `${response.status} ${JSON.stringify(data)}`
    );
  }

  return data;
}

async function main() {
  // Validate Photon credentials.
  const projectId = process.env.SPECTRUM_PROJECT_ID;
  const projectSecret = process.env.SPECTRUM_PROJECT_SECRET;

  if (!projectId || !projectSecret) {
    throw new Error(
      "Missing SPECTRUM_PROJECT_ID or " +
      "SPECTRUM_PROJECT_SECRET in .env"
    );
  }

  console.log("Checking Python backend:", bridge);
  await api("/health");
  console.log("Python backend connected. Connecting to Photon Spectrum...");
  const connectionWarning = setTimeout(() => {
    console.warn("Still waiting for Spectrum initialization. Check the project's iMessage connection and credentials in Photon.");
  }, 15000);
  // Initialize Spectrum.
  const app = await (async () => {
    try {
      return await Spectrum({
        projectId,
        projectSecret,
        providers: [imessage.config()],
      });
    } finally {
      clearTimeout(connectionWarning);
    }
  })();

  const im = imessage(app);

  let draining = false;

  /**
   * Deliver messages queued by the Python backend.
   *
   * For each message:
   * 1. Find the recipient's iMessage conversation.
   * 2. Send the message through Photon.
   * 3. Acknowledge delivery to the Python backend.
   */
  async function flushOutbox(): Promise<void> {
    if (draining) return;

    draining = true;

    try {
      const result = await api("/pending");

      const messages: OutgoingMessage[] = result.messages;

      for (const item of messages) {
        if (!item.space_id) {
          console.warn(
            "No iMessage conversation for:",
            item.recipient
          );
          continue;
        }

        try {
          const target = await im.space.get(item.space_id);

          await target.send(item.text);

          // Acknowledge only after the send succeeds.
          await api("/ack", {
            id: item.id,
          });

          console.log(
            `Sent message ${item.id} to ${item.recipient}`
          );
        } catch (error) {
          console.error(
            `Failed to deliver message ${item.id}:`,
            error
          );

          // Leave the message in the queue for retry.
        }
      }
    } catch (error) {
      console.error(
        "Python backend unavailable or outbox error:",
        error
      );
    } finally {
      draining = false;
    }
  }

  // Check for outgoing messages every 2.5 seconds.
  const timer = setInterval(() => {
    void flushOutbox();
  }, 2500);

  // Graceful shutdown.
  async function shutdown() {
    console.log("Shutting down PantryPulse...");

    clearInterval(timer);

    try {
      await app.stop();
    } catch (error) {
      console.error("Shutdown error:", error);
    }

    process.exit(0);
  }

  process.once("SIGINT", () => {
    void shutdown();
  });

  process.once("SIGTERM", () => {
    void shutdown();
  });

  console.log("-----------------------------------");
  console.log("PantryPulse iMessage Agent");
  console.log("-----------------------------------");
  console.log("Photon Spectrum initialized.");
  console.log("Python backend:", bridge);
  console.log("Waiting for incoming iMessages...");
  console.log("-----------------------------------");

  // Send any messages already queued.
  void flushOutbox();

  /**
   * Process incoming iMessages.
   */
  for await (const [space, message] of app.messages) {
    console.log("Spectrum event:", {
      platform: message.platform,
      direction: message.direction,
      contentType: message.content?.type,
      hasSender: Boolean(message.sender?.id),
    });
    // Don't respond to messages sent by the agent.
    if (message.direction === "outbound") {
      continue;
    }

    // Only handle iMessage.
    if (message.platform !== "imessage") {
      console.warn("Skipping event from platform:", message.platform);
      continue;
    }

    // Only process incoming text.
    if (message.content.type !== "text") {
      console.log("Skipping non-text event.");
      continue;
    }

    // Sender must have an identifier.
    if (!message.sender?.id) {
      console.warn("Skipping event without a sender ID.");
      continue;
    }

    const sender = message.sender.id;
    const text = message.content.text.trim();

    if (!text) continue;

    console.log("Incoming iMessage:", {
      sender,
      text,
      messageId: String(message.id),
    });

    try {
      // Send the incoming message to the Python backend.
      await api("/message", {
        handle: sender,
        space_id: space.id,
        message_id: String(message.id),
        text,
      });

      // Deliver any responses generated by the backend.
      await flushOutbox();
    } catch (error) {
      console.error(
        "Failed to process incoming message:",
        error
      );

      try {
        await space.send(
          "PantryPulse couldn't process your message. " +
          "Please try again shortly."
        );
      } catch (sendError) {
        console.error(
          "Failed to send error response:",
          sendError
        );
      }
    }
  }
}

main().catch((error) => {
  console.error("PantryPulse startup failed:", error);
  process.exitCode = 1;
});
