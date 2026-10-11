
import "dotenv/config";
import { Spectrum } from "spectrum-ts";
import { imessage } from "spectrum-ts/providers/imessage";

type Role = "donor" | "pantry";
type DonationStatus =
  | "offered"
  | "reserved"
  | "completed"
  | "unmatched";

type Donation = {
  id: number;
  description: string;
  status: DonationStatus;
  pantryIndex: number;
  pantryId: string | null;
};

async function main() {
  const projectId = process.env.SPECTRUM_PROJECT_ID;
  const projectSecret = process.env.SPECTRUM_PROJECT_SECRET;

  if (!projectId || !projectSecret) {
    throw new Error("Missing Photon credentials");
  }

  const app = await Spectrum({
    projectId,
    projectSecret,
    providers: [imessage.config()],
  });

  const im = imessage(app);

  // Temporary in-memory data for the hackathon test.
  const roles = new Map<string, Role>();
  const conversations = new Map<string, string>();
  const pantryIds: string[] = [];
  const processed = new Set<string>();

  let donorId: string | null = null;
  let donation: Donation | null = null;
  let nextDonationId = 104;

  // Send to a participant's existing iMessage conversation.
  async function sendTo(userId: string, text: string) {
    const spaceId = conversations.get(userId);

    if (!spaceId) {
      throw new Error(`No conversation registered for ${userId}`);
    }

    const chat = await im.space.get(spaceId);
    await chat.send(text);
  }

  // Offer the donation to the next registered test pantry.
  async function offerNextPantry() {
    if (!donation) return;

    const pantryId = pantryIds[donation.pantryIndex];

    if (!pantryId) {
      donation.status = "unmatched";
      donation.pantryId = null;

      if (donorId) {
        await sendTo(
          donorId,
          `No test pantry accepted donation #${donation.id}.`
        );
      }
      return;
    }

    donation.pantryId = pantryId;
    donation.status = "offered";

    await sendTo(
      pantryId,
      `FOODBRIDGE — TEST PANTRY OFFER\n\n` +
      `Donation #${donation.id}\n` +
      `${donation.description}\n\n` +
      `Reply ACCEPT ${donation.id} or PASS ${donation.id}.`
    );

    console.log("Offer sent:", donation.id, pantryId);
  }

  console.log("Foodbridge agent running.");
  console.log("Waiting for donor and pantry registrations...");

  for await (const [space, message] of app.messages) {
    if (message.direction === "outbound") continue;
    if (message.content.type !== "text") continue;

    const sender = message.sender?.id;
    if (!sender) continue;

    const messageKey = `${space.id}:${message.id}`;
    if (processed.has(messageKey)) continue;
    processed.add(messageKey);

    const text = message.content.text.trim();
    const upper = text.toUpperCase();

    console.log("Incoming:", {
      sender,
      space: space.id,
      text,
    });

    try {
      // Register a consenting test participant.
      if (upper === "JOIN DONOR" || upper === "JOIN PANTRY") {
        const role: Role =
          upper === "JOIN DONOR" ? "donor" : "pantry";

        const existingRole = roles.get(sender);

        if (existingRole && existingRole !== role) {
          await space.send(
            `You're already registered as ${existingRole}.`
          );
          continue;
        }

        if (role === "donor" && donorId && donorId !== sender) {
          await space.send(
            "A test donor is already registered."
          );
          continue;
        }

        if (role === "pantry" && sender === donorId) {
          await space.send(
            "The donor cannot also be a pantry in this test."
          );
          continue;
        }

        roles.set(sender, role);
        conversations.set(sender, space.id);

        if (role === "donor") {
          donorId = sender;

          await space.send(
            "Welcome to Foodbridge!\n\n" +
            "Describe your donation by texting:\n" +
            "DONATE 24 unopened cans of beans, " +
            "drop-off before 6 PM\n\n" +
            "Text STATUS to check your donation."
          );
        } else {
          if (!pantryIds.includes(sender)) {
            pantryIds.push(sender);
          }

          await space.send(
            "You've joined as a TEST PANTRY.\n\n" +
            "You'll receive donation offers here. " +
            "Reply ACCEPT or PASS with the offer number."
          );
        }

        console.log("Registered:", role, sender);
        continue;
      }

      const role = roles.get(sender);

      if (!role) {
        await space.send(
          "Welcome to Foodbridge. " +
          "Text JOIN DONOR or JOIN PANTRY to begin."
        );
        continue;
      }

      // DONOR COMMANDS
      if (role === "donor") {
        if (upper === "STATUS") {
          await space.send(
            donation
              ? `Donation #${donation.id}: ${donation.status}`
              : "You have no donation yet."
          );
          continue;
        }

        if (upper.startsWith("DONATE ")) {
          if (
            donation &&
            (donation.status === "offered" ||
              donation.status === "reserved")
          ) {
            await space.send(
              "Your previous donation is still active. " +
              "Text STATUS for an update."
            );
            continue;
          }

          if (pantryIds.length === 0) {
            await space.send(
              "No test pantry has registered yet. " +
              "Please ask the pantry tester to join first."
            );
            continue;
          }

          const description = text.slice(7).trim();

          if (!/\b(unopened|sealed)\b/i.test(description)) {
            await space.send(
              "For this prototype, please describe unopened " +
              "or sealed shelf-stable food."
            );
            continue;
          }

          donation = {
            id: nextDonationId++,
            description,
            status: "offered",
            pantryIndex: 0,
            pantryId: null,
          };

          await space.send(
            `Donation #${donation.id} recorded. ` +
            "I'm contacting a test pantry now."
          );

          await offerNextPantry();
          continue;
        }

        await space.send(
          "Text DONATE followed by a food description, " +
          "or text STATUS."
        );
        continue;
      }

      // PANTRY COMMANDS
      if (role === "pantry") {
        const currentDonation = donation;

        if (
          !currentDonation ||
          currentDonation.pantryId !== sender
        ) {
          await space.send(
            "You don't have an active offer assigned to you."
          );
          continue;
        }

        const offerId = currentDonation.id;

        if (
          upper === `PASS ${offerId}` &&
          currentDonation.status === "offered"
        ) {
          await space.send(
            `Declined offer #${offerId}. Thank you for responding.`
          );

          currentDonation.pantryIndex++;
          await offerNextPantry();
          continue;
        }

        if (
          upper === `ACCEPT ${offerId}` &&
          currentDonation.status === "offered"
        ) {
          currentDonation.status = "reserved";

          await space.send(
            `Donation #${offerId} reserved for your test pantry.\n` +
            `Reply RECEIVED ${offerId} after the simulated handoff.`
          );

          if (donorId) {
            await sendTo(
              donorId,
              `Good news! A test pantry accepted donation #${offerId}.\n` +
              "This is a simulated handoff, not a real delivery."
            );
          }
          continue;
        }

        if (
          upper === `RECEIVED ${offerId}` &&
          currentDonation.status === "reserved"
        ) {
          currentDonation.status = "completed";

          await space.send(
            `Donation #${offerId} marked completed.`
          );

          if (donorId) {
            await sendTo(
              donorId,
              `Donation #${offerId} is completed.`
            );
          }
          continue;
        }

        await space.send(
          `No valid action for this offer.\n` +
          `Use ACCEPT ${offerId}, PASS ${offerId}, ` +
          `or RECEIVED ${offerId} when appropriate.`
        );
      }
    } catch (error) {
      console.error("Foodbridge message error:", error);
      try {
        await space.send(
          "I couldn't complete that action. Please try again."
        );
      } catch (replyError) {
        console.error("Error sending failure reply:", replyError);
      }
    }
  }
}

main().catch(console.error);
