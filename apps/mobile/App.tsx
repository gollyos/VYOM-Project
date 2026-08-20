/**
 * VYOM Mobile Companion — Phase 12 scaffold.
 *
 * Mobile is NOT a clone of the desktop neural canvas. The home screen
 * is a simplified VYOM Core presence ("Ready"), voice-first command,
 * critical status, approvals, and quick commands. See
 * docs/MOBILE_COMPANION.md for the full contract.
 */
import React, { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { vyomClient, VyomStatus, RemoteApproval, OfflineQueue, PairingTicket, isPaired, startPairing, claimPairing } from "./src/vyom";

export default function App() {
  const [connected, setConnected] = useState(false);
  const [status, setStatus] = useState<VyomStatus | null>(null);
  const [approvals, setApprovals] = useState<RemoteApproval[]>([]);
  const [message, setMessage] = useState("Ready");
  const [busy, setBusy] = useState(false);
  const [paired, setPaired] = useState<boolean | null>(null);
  const [brainUrl, setBrainUrl] = useState("https://vyom.local");
  const [pairingTicket, setPairingTicket] = useState<PairingTicket | null>(null);

  useEffect(() => {
    const poll = async () => {
      const pairedNow = await isPaired();
      setPaired(pairedNow);
      if (!pairedNow) return;
      const ok = await vyomClient.checkHealth();
      setConnected(ok);
      if (!ok) return;
      setStatus(await vyomClient.status());
      setApprovals(await vyomClient.approvals());
      await OfflineQueue.flush(vyomClient);
      const deliveries = await vyomClient.deliveries();
      if (deliveries.length) {
        const latest = deliveries[deliveries.length - 1];
        setMessage(latest.payload.summary ?? `Task ${latest.payload.status ?? "updated"}`);
        for (const delivery of deliveries) await vyomClient.acknowledge(delivery.delivery_id);
      }
    };
    poll();
    const timer = setInterval(poll, 15000);
    return () => clearInterval(timer);
  }, []);

  const runCommand = async (command: string) => {
    setBusy(true);
    try {
      if (connected) {
        const result = await vyomClient.command(command);
        setMessage(result.summary ?? "Done");
      } else {
        // Offline: queue locally, never present cached data as live.
        await OfflineQueue.enqueue(command);
        setMessage("Offline — command queued");
      }
    } finally {
      setBusy(false);
    }
  };

  const decide = async (taskId: string, decision: string) => {
    await vyomClient.decideApproval(taskId, decision, /* strongVerification */ false);
    setApprovals(await vyomClient.approvals());
  };

  const beginPairing = async () => {
    setBusy(true);
    try {
      const ticket = await startPairing(brainUrl);
      setPairingTicket(ticket);
      setMessage("Approve this phone on the PC, then tap Finish pairing");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Pairing failed");
    } finally { setBusy(false); }
  };

  const finishPairing = async () => {
    if (!pairingTicket) return;
    setBusy(true);
    try {
      const claimed = await claimPairing(pairingTicket);
      if (!claimed) setMessage("Still waiting for approval on the PC");
      else { setPaired(true); setMessage("Phone securely paired"); }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Pairing failed");
    } finally { setBusy(false); }
  };

  if (paired === false) return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <Text style={styles.identity}>VYOM</Text>
      <Text style={styles.connection}>Secure phone pairing</Text>
      <View style={styles.pairingCard}>
        <Text style={styles.sectionTitle}>PC Brain address</Text>
        <TextInput value={brainUrl} onChangeText={setBrainUrl} autoCapitalize="none" autoCorrect={false} style={styles.input} />
        <Pressable style={styles.voiceButton} onPress={beginPairing}><Text style={styles.voiceLabel}>Start pairing</Text></Pressable>
        {pairingTicket ? <>
          <Text style={styles.pairingCode}>{pairingTicket.code}</Text>
          <Text style={styles.statusLine}>Confirm request {pairingTicket.request_id} on your PC.</Text>
          <Pressable style={styles.approve} onPress={finishPairing}><Text style={styles.rowLabel}>Finish pairing</Text></Pressable>
        </> : null}
        {busy ? <ActivityIndicator color="#67e8f9" /> : null}<Text style={styles.coreState}>{message}</Text>
      </View>
    </ScrollView>
  );

  if (paired === null) return (
    <View style={[styles.screen, styles.loading]}><ActivityIndicator color="#67e8f9" /></View>
  );

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <Text style={styles.identity}>VYOM</Text>
      <Text style={styles.connection}>{connected ? "Online" : "Offline — cached"}</Text>

      <View style={styles.core}>
        {busy ? <ActivityIndicator color="#67e8f9" /> : <View style={styles.coreOrb} />}
        <Text style={styles.coreState}>{message}</Text>
        {status ? (
          <Text style={styles.statusLine}>
            {status.tasks_running} running · {status.agents_working} agents · {approvals.length} approvals
          </Text>
        ) : null}
      </View>

      <Pressable style={styles.voiceButton} onPress={() => runCommand("What's happening?")}>
        <Text style={styles.voiceLabel}>Hold to speak</Text>
      </Pressable>

      {approvals.length > 0 ? (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Waiting for approval</Text>
          {approvals.map((approval) => (
            <View key={approval.task_id} style={styles.approval}>
              <Text style={styles.approvalAction}>{approval.requested_action}</Text>
              <Text style={styles.approvalMeta}>
                Risk {approval.risk} · {approval.permission_level}
                {approval.requires_strong_verification ? " · biometric required" : ""}
              </Text>
              <View style={styles.approvalRow}>
                <Pressable style={styles.approve} onPress={() => decide(approval.task_id, "approve")}>
                  <Text style={styles.rowLabel}>Approve</Text>
                </Pressable>
                <Pressable style={styles.reject} onPress={() => decide(approval.task_id, "reject")}>
                  <Text style={styles.rowLabel}>Reject</Text>
                </Pressable>
                <Pressable style={styles.secondary} onPress={() => decide(approval.task_id, "pause")}>
                  <Text style={styles.rowLabel}>Pause</Text>
                </Pressable>
              </View>
            </View>
          ))}
        </View>
      ) : null}

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Quick commands</Text>
        {[
          "What's happening?",
          "What needs approval?",
          "Today's plan",
          "Agent status",
          "Pause VYOM",
        ].map((quick) => (
          <Pressable key={quick} style={styles.quick} onPress={() => runCommand(quick)}>
            <Text style={styles.quickLabel}>{quick}</Text>
          </Pressable>
        ))}
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: "#04070b" },
  content: { padding: 24, gap: 16 },
  identity: { color: "#e2f5ff", fontSize: 28, fontWeight: "300", letterSpacing: 8, marginTop: 32 },
  connection: { color: "#5f7d8c", fontSize: 12, letterSpacing: 2 },
  core: { alignItems: "center", gap: 10, paddingVertical: 24 },
  coreOrb: {
    width: 84, height: 84, borderRadius: 42,
    backgroundColor: "#0b2b33", borderWidth: 1, borderColor: "#1e5f6e",
    shadowColor: "#67e8f9", shadowOpacity: 0.5, shadowRadius: 24,
  },
  coreState: { color: "#9fd7e8", fontSize: 15 },
  statusLine: { color: "#5f7d8c", fontSize: 12 },
  voiceButton: {
    backgroundColor: "#0b2b33", borderRadius: 999, paddingVertical: 14, alignItems: "center",
    borderWidth: 1, borderColor: "#1e5f6e",
  },
  voiceLabel: { color: "#67e8f9", fontSize: 13, letterSpacing: 2 },
  section: { gap: 8, marginTop: 12 },
  sectionTitle: { color: "#7d9db0", fontSize: 12, letterSpacing: 2, textTransform: "uppercase" },
  approval: { backgroundColor: "#071018", borderRadius: 12, padding: 14, gap: 6, borderWidth: 1, borderColor: "#122b33" },
  approvalAction: { color: "#d8ecf5", fontSize: 14 },
  approvalMeta: { color: "#6b8a99", fontSize: 11 },
  approvalRow: { flexDirection: "row", gap: 8, marginTop: 4 },
  approve: { backgroundColor: "#0c3b2e", borderRadius: 8, paddingHorizontal: 14, paddingVertical: 8 },
  reject: { backgroundColor: "#3b1519", borderRadius: 8, paddingHorizontal: 14, paddingVertical: 8 },
  secondary: { backgroundColor: "#152029", borderRadius: 8, paddingHorizontal: 14, paddingVertical: 8 },
  rowLabel: { color: "#cfe7f2", fontSize: 12 },
  quick: { backgroundColor: "#071018", borderRadius: 10, paddingHorizontal: 14, paddingVertical: 12, borderWidth: 1, borderColor: "#122b33" },
  quickLabel: { color: "#9fd7e8", fontSize: 13 },
  pairingCard: { gap: 12, marginTop: 32, padding: 18, borderRadius: 12, borderWidth: 1, borderColor: "#122b33", backgroundColor: "#071018" },
  input: { color: "#d8ecf5", borderWidth: 1, borderColor: "#1e5f6e", borderRadius: 8, paddingHorizontal: 12, paddingVertical: 10 },
  pairingCode: { color: "#67e8f9", fontSize: 26, letterSpacing: 5, textAlign: "center" },
  loading: { alignItems: "center", justifyContent: "center" },
});
