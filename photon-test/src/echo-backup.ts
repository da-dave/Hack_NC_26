
import "dotenv/config";
import { Spectrum } from "spectrum-ts";
import { imessage } from "spectrum-ts/providers/imessage";

async function main() {
  const projectId = process.env.SPECTRUM_PROJECT_ID;
  const projectSecret = process.env.SPECTRUM_PROJECT_SECRET;

  if (!projectId || !projectSecret) {
    throw new Error("Missing Photon credentials in .env");
  }

  const app = await Spectrum({
    projectId,
    projectSecret,
    providers: [imessage.config()],
  });

  console.log("Foodbridge Photon agent started.");
  console.log("Waiting for incoming iMessages...");

  for await (const [space, message] of app.messages) {
    if (message.direction === "outbound") continue;
    if (message.content.type !== "text") continue;

    const incomingText = message.content.text;
    console.log("Received:", incomingText);

    try {
      await space.send(`echo: ${incomingText}`);
      console.log("Reply sent.");
    } catch (error) {
      console.error("Failed to send reply:", error);
    }
  }
}

main().catch((error) => {
  console.error("Photon startup error:", error);
  process.exitCode = 1;
});
