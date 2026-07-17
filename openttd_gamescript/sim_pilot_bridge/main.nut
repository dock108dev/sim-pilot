class SimPilotBridge extends GSController {
    protocol_version = 1;
    sequence = 0;
    instance_id = null;
    loaded = false;
    save_generation = 0;
    start_generation = 0;
    active_company = null;
    last_snapshot_id = null;
    command_ledger = null;
    ledger_limit = 64;
    capability_fingerprint = "a4868cb5227ad0e126764cb2312b52573218087ab6f5d145a7c8a60877db55ca";

    constructor() {
        this.command_ledger = [];
    }

    function Start() {
        if (this.instance_id == null) {
            this.instance_id = "spb-" + GSBase.Rand() + "-" + GSBase.Rand();
        }
        this.start_generation++;
        this.SendHello(null);
        this.SendCapabilities(null);
        while (true) {
            while (GSEventController.IsEventWaiting()) {
                local event = GSEventController.GetNextEvent();
                if (event.GetEventType() == GSEvent.ET_ADMIN_PORT) {
                    this.HandleMessage(GSEventAdminPort.Convert(event).GetObject());
                }
            }
            if (GSController.GetTick() % 300 == 0) {
                this.Send("heartbeat", null, this.active_company, {
                    tick = GSController.GetTick(),
                    snapshot_id = this.last_snapshot_id,
                    healthy = true
                });
            }
            this.Sleep(1);
        }
    }

    function Send(kind, correlation, company, payload) {
        this.sequence++;
        return GSAdmin.Send({
            protocol_version = this.protocol_version,
            sequence = this.sequence,
            message_id = this.instance_id + ":" + this.sequence,
            correlation_id = correlation,
            script_instance_id = this.instance_id,
            message_type = kind,
            game_date = GSDate.GetCurrentDate(),
            company_id = company,
            payload = payload
        });
    }

    function SendHello(correlation) {
        this.Send("hello", correlation, this.active_company, {
            component = "sim_pilot_bridge",
            openttd_version = "15.3",
            gamescript_api_version = "15",
            script_version = 1,
            adapter_version = "openttd-gamescript-v1",
            loaded = this.loaded,
            save_generation = this.save_generation,
            start_generation = this.start_generation
        });
    }

    function SendCapabilities(correlation) {
        this.Send("capabilities", correlation, this.active_company, {
            capability_version = 1,
            readable_resources = [
                "paused", "map_width", "map_height", "town_count", "industry_count",
                "company_name", "company_cash", "company_loan", "vehicle_count",
                "station_count"
            ],
            readable_entities = ["company", "town_summary", "industry_summary"],
            event_types = [],
            supported_actions = ["set_company_name"],
            company_contexts = ["existing_company"],
            cost_estimation = true,
            independent_verification = true,
            reconciliation = true,
            save_load = true,
            full_snapshots = true,
            state_deltas = false,
            maximum_outbound_bytes = 1450,
            maximum_inbound_bytes = 8999,
            write_opt_in_required = true
        });
    }

    function HandleMessage(message) {
        if (!this.HasExactKeys(message, [
                "protocol_version", "sequence", "message_id", "correlation_id",
                "script_instance_id", "message_type", "game_date", "company_id", "payload"
            ]) || typeof message.protocol_version != "integer" ||
                typeof message.sequence != "integer" || message.sequence < 1 ||
                typeof message.message_id != "string" || message.message_id.len() == 0 ||
                typeof message.script_instance_id != "string" ||
                typeof message.message_type != "string" ||
                typeof message.game_date != "integer" || message.game_date < 0 ||
                typeof message.payload != "table" ||
                (message.correlation_id != null && typeof message.correlation_id != "string") ||
                (message.company_id != null && typeof message.company_id != "integer")) {
            this.SendError(null, "protocol_mismatch", "invalid bridge envelope", null, null);
            return;
        }
        if (message.protocol_version != this.protocol_version) {
            this.SendError(message.message_id, "protocol_mismatch", "unsupported protocol", null, null);
            return;
        }
        if (message.rawin("company_id") && message.company_id != null) {
            this.active_company = message.company_id;
        }
        if (message.message_type == "resync_request") {
            this.HandleResync(message);
        } else if (message.message_type == "command_request") {
            this.HandleCommand(message);
        } else {
            this.SendError(
                message.message_id,
                "unsupported_command",
                "unsupported message type",
                null,
                null
            );
        }
    }

    function HandleResync(message) {
        if (!this.HasExactKeys(message.payload, [
                "last_script_instance_id", "last_sequence", "reason"
            ]) || typeof message.payload.reason != "string") {
            this.SendError(
                message.message_id, "invalid_parameters", "invalid resync payload", null, null
            );
            return;
        }
        this.SendHello(message.message_id);
        this.SendCapabilities(message.message_id);
        this.Send("resync_response", message.message_id, this.active_company, {
            snapshot_follows = true,
            reason = message.payload.rawin("reason") ? message.payload.reason : "requested"
        });
        this.SendSnapshot();
    }

    function SendSnapshot() {
        local company = this.BuildCompanySnapshot(this.active_company);
        local next_sequence = this.sequence + 1;
        this.last_snapshot_id = this.instance_id + ":snapshot:" + next_sequence;
        this.Send("state_snapshot", null, this.active_company, {
            snapshot_id = this.last_snapshot_id,
            paused = GSGame.IsPaused(),
            map_width = GSMap.GetMapSizeX(),
            map_height = GSMap.GetMapSizeY(),
            town_count = GSTown.GetTownCount(),
            industry_count = GSIndustry.GetIndustryCount(),
            company = company,
            save_generation = this.save_generation
        });
    }

    function BuildCompanySnapshot(company) {
        if (company == null || GSCompany.ResolveCompanyID(company) == GSCompany.COMPANY_INVALID) {
            return null;
        }
        local result = null;
        {
            local mode = GSCompanyMode(company);
            if (!GSCompanyMode.IsValid()) return null;
            result = {
                company_id = company,
                name = GSCompany.GetName(company),
                cash = GSCompany.GetBankBalance(company),
                loan = GSCompany.GetLoanAmount(),
                vehicle_count = GSVehicleList().Count(),
                station_count = GSStationList(GSStation.STATION_ANY).Count()
            };
        }
        return result;
    }

    function HandleCommand(message) {
        local payload = message.payload;
        if (!this.HasExactKeys(payload, [
                "command_id", "action", "parameters", "action_fingerprint",
                "expected_capability_fingerprint", "expected_company_id",
                "prior_snapshot_id", "request_timestamp"
            ]) || typeof payload.command_id != "string" || payload.command_id.len() == 0 ||
                typeof payload.action != "string" || typeof payload.parameters != "table" ||
                typeof payload.action_fingerprint != "string" ||
                typeof payload.expected_capability_fingerprint != "string" ||
                typeof payload.expected_company_id != "integer" ||
                typeof payload.prior_snapshot_id != "string" ||
                typeof payload.request_timestamp != "string" ||
                !this.HasExactKeys(payload.parameters, ["name"])) {
            this.SendError(
                message.message_id, "invalid_parameters", "missing command field", null, null
            );
            return;
        }
        local prior = this.FindLedger(payload.command_id);
        if (prior != null) {
            if (prior.action_fingerprint != payload.action_fingerprint) {
                this.SendError(
                    message.message_id,
                    "duplicate_conflict",
                    "command ID has a different fingerprint",
                    payload.command_id,
                    payload.action_fingerprint
                );
                return;
            }
            this.SendAccepted(message.message_id, prior.command_id, prior.action_fingerprint);
            this.SendCompleted(message.message_id, prior, true);
            return;
        }
        if (payload.action != "set_company_name") {
            this.SendError(
                message.message_id,
                "unsupported_command",
                "action is not supported",
                payload.command_id,
                payload.action_fingerprint
            );
            return;
        }
        if (payload.expected_capability_fingerprint != this.capability_fingerprint) {
            this.SendError(
                message.message_id,
                "stale_request",
                "capability fingerprint changed",
                payload.command_id,
                payload.action_fingerprint
            );
            return;
        }
        if (this.active_company == null || payload.expected_company_id != this.active_company ||
                GSCompany.ResolveCompanyID(this.active_company) == GSCompany.COMPANY_INVALID) {
            this.SendError(
                message.message_id,
                "invalid_company",
                "selected company is unavailable",
                payload.command_id,
                payload.action_fingerprint
            );
            return;
        }
        if (payload.prior_snapshot_id != this.last_snapshot_id) {
            this.SendError(
                message.message_id,
                "stale_request",
                "snapshot identity changed",
                payload.command_id,
                payload.action_fingerprint
            );
            return;
        }
        if (!payload.parameters.rawin("name") || typeof payload.parameters.name != "string" ||
                payload.parameters.name.len() == 0 || payload.parameters.name.len() > 128) {
            this.SendError(
                message.message_id,
                "invalid_parameters",
                "name must be a non-empty string no longer than 128 bytes",
                payload.command_id,
                payload.action_fingerprint
            );
            return;
        }
        this.ExecuteSetCompanyName(message, payload);
    }

    function ExecuteSetCompanyName(message, payload) {
        local before_name = null;
        local after_name = null;
        local test_success = false;
        local cost = 0;
        local success = false;
        {
            local mode = GSCompanyMode(this.active_company);
            if (!GSCompanyMode.IsValid()) {
                this.SendError(
                    message.message_id,
                    "context_unavailable",
                    "company context is invalid",
                    payload.command_id,
                    payload.action_fingerprint
                );
                return;
            }
            before_name = GSCompany.GetName(this.active_company);
            {
                local accounting = GSAccounting();
                local test_mode = GSTestMode();
                test_success = GSCompany.SetName(payload.parameters.name);
                cost = accounting.GetCosts();
            }
            if (!test_success || GSCompany.GetName(this.active_company) != before_name) {
                this.SendError(
                    message.message_id,
                    "game_rule_rejection",
                    "test mode rejected or changed state",
                    payload.command_id,
                    payload.action_fingerprint
                );
                return;
            }
            this.SendAccepted(message.message_id, payload.command_id, payload.action_fingerprint);
            success = GSCompany.SetName(payload.parameters.name);
            after_name = GSCompany.GetName(this.active_company);
        }
        if (!success || after_name != payload.parameters.name) {
            this.Send("command_failed", message.message_id, this.active_company, {
                code = "game_rule_rejection",
                message = "OpenTTD rejected the company name",
                command_id = payload.command_id,
                action_fingerprint = payload.action_fingerprint,
                retryable = false
            });
            return;
        }
        local record = {
            command_id = payload.command_id,
            action_fingerprint = payload.action_fingerprint,
            before_name = before_name,
            after_name = after_name,
            state_changed = before_name != after_name,
            cost = cost
        };
        this.Remember(record);
        this.SendCompleted(message.message_id, record, false);
    }

    function SendAccepted(correlation, command_id, fingerprint) {
        this.Send("command_accepted", correlation, this.active_company, {
            command_id = command_id,
            action_fingerprint = fingerprint
        });
    }

    function SendCompleted(correlation, record, duplicate) {
        this.Send("command_completed", correlation, this.active_company, {
            command_id = record.command_id,
            action_fingerprint = record.action_fingerprint,
            action = "set_company_name",
            before_name = record.before_name,
            after_name = record.after_name,
            state_changed = record.state_changed,
            cost = record.cost,
            duplicate = duplicate
        });
    }

    function SendError(correlation, code, message, command_id, fingerprint) {
        local kind = correlation == null ? "error" : "command_rejected";
        this.Send(kind, correlation, this.active_company, {
            code = code,
            message = message,
            command_id = command_id,
            action_fingerprint = fingerprint,
            retryable = false
        });
    }

    function FindLedger(command_id) {
        foreach (record in this.command_ledger) {
            if (record.command_id == command_id) return record;
        }
        return null;
    }

    function Remember(record) {
        this.command_ledger.append(record);
        if (this.command_ledger.len() > this.ledger_limit) this.command_ledger.remove(0);
    }

    function HasExactKeys(value, keys) {
        if (value == null || typeof value != "table" || value.len() != keys.len()) return false;
        foreach (key in keys) {
            if (!value.rawin(key)) return false;
        }
        return true;
    }

    function Save() {
        this.save_generation++;
        return {
            protocol_version = this.protocol_version,
            sequence = this.sequence,
            instance_id = this.instance_id,
            save_generation = this.save_generation,
            start_generation = this.start_generation,
            active_company = this.active_company,
            last_snapshot_id = this.last_snapshot_id,
            command_ledger = this.command_ledger
        };
    }

    function Load(version, data) {
        this.loaded = true;
        if (data == null || !data.rawin("protocol_version") || data.protocol_version != 1) {
            this.sequence = 0;
            this.instance_id = null;
            this.save_generation = 0;
            this.start_generation = 0;
            this.active_company = null;
            this.last_snapshot_id = null;
            this.command_ledger = [];
            return;
        }
        this.sequence = data.rawin("sequence") ? data.sequence : 0;
        this.instance_id = data.rawin("instance_id") ? data.instance_id : null;
        this.save_generation = data.rawin("save_generation") ? data.save_generation : 0;
        this.start_generation = data.rawin("start_generation") ? data.start_generation : 0;
        this.active_company = data.rawin("active_company") ? data.active_company : null;
        this.last_snapshot_id = data.rawin("last_snapshot_id") ? data.last_snapshot_id : null;
        this.command_ledger = data.rawin("command_ledger") ? data.command_ledger : [];
        while (this.command_ledger.len() > this.ledger_limit) this.command_ledger.remove(0);
    }
}
