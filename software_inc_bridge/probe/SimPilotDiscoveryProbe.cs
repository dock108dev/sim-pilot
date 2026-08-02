using System;
using System.Threading;
using UnityEngine;

namespace SimPilotSoftwareIncProbe
{
    public sealed class SimPilotProbeMeta : ModMeta
    {
        public override string Name
        {
            get { return "Sim Pilot Discovery Probe"; }
        }

        public override void ConstructOptionsScreen(RectTransform parent, bool inGame)
        {
        }
    }

    public sealed class SimPilotProbeBehaviour : ModBehaviour
    {
        public override void OnActivate()
        {
            Log("activated");
            GameSettings.GameReady += OnGameReady;
        }

        public override void OnDeactivate()
        {
            GameSettings.GameReady -= OnGameReady;
            Log("deactivated");
        }

        private static void OnGameReady(object sender, EventArgs eventArgs)
        {
            Log("game_ready");
        }

        private static void Log(string eventName)
        {
            Debug.Log(
                "SIM_PILOT_SOFTWARE_INC_PROBE schema=1 event=" + eventName +
                " thread=" + Thread.CurrentThread.ManagedThreadId +
                " version=" + Versioning.Major + "." + Versioning.Minor + "." + Versioning.Revision +
                " version_type=" + Versioning.Type
            );
        }
    }
}
