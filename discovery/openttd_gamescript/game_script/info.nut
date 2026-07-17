class SimPilotGSDiscoveryInfo extends GSInfo {
    function GetAuthor() { return "Sim Pilot Task 7A"; }
    function GetName() { return "SimPilotGSDiscovery"; }
    function GetDescription() { return "Disposable GameScript capability probe."; }
    function GetVersion() { return 1; }
    function MinVersionToLoad() { return 1; }
    function GetDate() { return "2026-07-16"; }
    function CreateInstance() { return "SimPilotGSDiscovery"; }
    function GetShortName() { return "SPGD"; }
    function GetAPIVersion() { return "15"; }
}

RegisterGS(SimPilotGSDiscoveryInfo());
