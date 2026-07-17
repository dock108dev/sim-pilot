class SimPilotBridgeInfo extends GSInfo {
    function GetAuthor() { return "Sim Pilot"; }
    function GetName() { return "SimPilotBridge"; }
    function GetDescription() { return "Versioned local telemetry and constrained command bridge."; }
    function GetVersion() { return 1; }
    function MinVersionToLoad() { return 1; }
    function GetDate() { return "2026-07-16"; }
    function CreateInstance() { return "SimPilotBridge"; }
    function GetShortName() { return "SPBR"; }
    function GetAPIVersion() { return "15"; }
}

RegisterGS(SimPilotBridgeInfo());
