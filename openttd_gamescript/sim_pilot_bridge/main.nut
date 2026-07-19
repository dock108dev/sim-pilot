class SimPilotBridge extends GSController {
    protocol_version = 2;
    sequence = 0;
    instance_id = null;
    loaded = false;
    save_generation = 0;
    start_generation = 0;
    active_company = null;
    last_snapshot_id = null;
    command_ledger = null;
    ledger_limit = 64;
    capability_fingerprint = "c7e830e62f9898d01704396f91785c9e4a6e9abf87cc08799f8f49a4d4103ec6";

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
            script_version = 2,
            adapter_version = "openttd-gamescript-v2",
            loaded = this.loaded,
            save_generation = this.save_generation,
            start_generation = this.start_generation
        });
    }

    function SendCapabilities(correlation) {
        this.Send("capabilities", correlation, this.active_company, {
            capability_version = 2,
            readable_resources = [
                "paused", "map_width", "map_height", "town_count", "industry_count",
                "company_name", "company_cash", "company_loan", "vehicle_count",
                "station_count"
            ],
            readable_entities = [
                "company", "town", "industry", "station", "vehicle", "order", "cargo"
            ],
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
            write_opt_in_required = true,
            world_snapshots = true,
            world_collections = [
                "companies", "towns", "industries", "stations", "vehicles", "orders", "cargos"
            ]
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
        if (message.protocol_version != this.protocol_version && message.protocol_version != 1) {
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
        this.SendWorldSnapshot();
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

    function SendWorldSnapshot() {
        local capture_started = GSDate.GetCurrentDate();
        local world_id = this.instance_id + ":world:" + (this.sequence + 1);
        local collections = this.BuildWorldCollections();
        local counts = {};
        local total = 0;
        foreach (name, items in collections) {
            counts[name] <- items.len();
            total += items.len();
        }
        this.Send("world_manifest", null, this.active_company, {
            snapshot_id = world_id,
            capture_started_game_date = capture_started,
            collection_counts = counts
        });
        local sent = 0;
        foreach (name, items in collections) {
            local count = items.len();
            for (local index = 0; index < count; index++) {
                this.Send("world_collection_page", null, this.active_company, {
                    snapshot_id = world_id,
                    collection = name,
                    page_index = index,
                    page_count = count,
                    items = [items[index]]
                });
                sent++;
                if (sent % 8 == 0) this.Sleep(1);
            }
        }
        this.Send("world_snapshot_complete", null, this.active_company, {
            snapshot_id = world_id,
            capture_completed_game_date = GSDate.GetCurrentDate(),
            total_items = total
        });
    }

    function BuildWorldCollections() {
        local result = {
            companies = [], towns = [], industries = [], stations = [],
            vehicles = [], orders = [], cargos = []
        };
        foreach (cargo_id, unused in GSCargoList()) {
            result.cargos.append({
                entity_type = "cargo", id = cargo_id, name = GSCargo.GetName(cargo_id),
                scope = "world", scope_entity_id = null, waiting = null, produced = null,
                accepted = null, transported = null, transported_percent = null
            });
        }
        foreach (company_id, unused in GSCompanyList()) {
            local loan = 0;
            local station_count = 0;
            local hq = GSCompany.GetCompanyHQ(company_id);
            {
                local mode = GSCompanyMode(company_id);
                if (GSCompanyMode.IsValid()) {
                    loan = GSCompany.GetLoanAmount();
                    station_count = GSStationList(GSStation.STATION_ANY).Count();
                }
            }
            result.companies.append({
                entity_type = "company", id = company_id, name = GSCompany.GetName(company_id),
                cash = GSCompany.GetBankBalance(company_id), loan = loan,
                company_value = GSCompany.GetQuarterlyCompanyValue(company_id, 1),
                income = GSCompany.GetQuarterlyIncome(company_id, 0),
                expenses = GSCompany.GetQuarterlyExpenses(company_id, 0),
                performance = GSCompany.GetQuarterlyPerformanceRating(company_id, 1),
                headquarters_tile = GSMap.IsValidTile(hq) ? hq : null,
                station_count = station_count
            });
        }
        foreach (town_id, unused in GSTownList()) {
            local rating = null;
            if (this.active_company != null &&
                    GSCompany.ResolveCompanyID(this.active_company) != GSCompany.COMPANY_INVALID) {
                rating = GSTown.GetDetailedRating(town_id, this.active_company);
            }
            result.towns.append({
                entity_type = "town", id = town_id, name = GSTown.GetName(town_id),
                population = GSTown.GetPopulation(town_id), tile = GSTown.GetLocation(town_id),
                growth_rate = GSTown.GetGrowthRate(town_id), rating = rating
            });
            foreach (cargo_id, unused_cargo in GSCargoList()) {
                local produced = GSTown.GetLastMonthProduction(town_id, cargo_id);
                if (produced > 0) {
                    result.cargos.append({
                        entity_type = "cargo", id = cargo_id, name = GSCargo.GetName(cargo_id),
                        scope = "town", scope_entity_id = town_id, waiting = null,
                        produced = produced, accepted = null, transported = null,
                        transported_percent = GSTown.GetLastMonthTransportedPercentage(
                            town_id, cargo_id
                        )
                    });
                }
            }
        }
        foreach (industry_id, unused in GSIndustryList()) {
            local accepted = [];
            local produced_cargos = [];
            foreach (cargo_id, unused_cargo in GSCargoList()) {
                if (GSIndustry.IsCargoAccepted(industry_id, cargo_id) !=
                        GSIndustry.CAS_NOT_ACCEPTED) accepted.append(cargo_id);
                local amount = GSIndustry.GetLastMonthProduction(industry_id, cargo_id);
                if (amount > 0) {
                    produced_cargos.append(cargo_id);
                    result.cargos.append({
                        entity_type = "cargo", id = cargo_id, name = GSCargo.GetName(cargo_id),
                        scope = "industry", scope_entity_id = industry_id, waiting = null,
                        produced = amount, accepted = null,
                        transported = GSIndustry.GetLastMonthTransported(industry_id, cargo_id),
                        transported_percent = GSIndustry.GetLastMonthTransportedPercentage(
                            industry_id, cargo_id
                        )
                    });
                }
            }
            result.industries.append({
                entity_type = "industry", id = industry_id,
                industry_type = GSIndustry.GetIndustryType(industry_id),
                name = GSIndustry.GetName(industry_id), tile = GSIndustry.GetLocation(industry_id),
                nearby_station_count = GSIndustry.GetAmountOfStationsAround(industry_id),
                accepted_cargo_ids = accepted, produced_cargo_ids = produced_cargos
            });
        }
        if (this.active_company != null &&
                GSCompany.ResolveCompanyID(this.active_company) != GSCompany.COMPANY_INVALID) {
            local mode = GSCompanyMode(this.active_company);
            if (GSCompanyMode.IsValid()) this.BuildCompanyEntities(result);
        }
        return result;
    }

    function BuildCompanyEntities(result) {
        foreach (station_id, unused in GSStationList(GSStation.STATION_ANY)) {
            local facilities = [];
            if (GSStation.HasStationType(station_id, GSStation.STATION_TRAIN)) facilities.append("rail");
            if (GSStation.HasStationType(station_id, GSStation.STATION_TRUCK_STOP)) facilities.append("truck");
            if (GSStation.HasStationType(station_id, GSStation.STATION_BUS_STOP)) facilities.append("bus");
            if (GSStation.HasStationType(station_id, GSStation.STATION_AIRPORT)) facilities.append("airport");
            if (GSStation.HasStationType(station_id, GSStation.STATION_DOCK)) facilities.append("dock");
            result.stations.append({
                entity_type = "station", id = station_id,
                name = GSBaseStation.GetName(station_id), owner = GSBaseStation.GetOwner(station_id),
                tile = GSBaseStation.GetLocation(station_id), facilities = facilities
            });
            foreach (cargo_id, unused_cargo in GSCargoList()) {
                local waiting = GSStation.GetCargoWaiting(station_id, cargo_id);
                if (waiting > 0) {
                    result.cargos.append({
                        entity_type = "cargo", id = cargo_id, name = GSCargo.GetName(cargo_id),
                        scope = "station", scope_entity_id = station_id, waiting = waiting,
                        produced = null, accepted = null, transported = null,
                        transported_percent = null
                    });
                }
            }
        }
        foreach (vehicle_id, unused in GSVehicleList()) {
            if (!GSVehicle.IsPrimaryVehicle(vehicle_id)) continue;
            local current = GSOrder.ResolveOrderPosition(vehicle_id, GSOrder.ORDER_CURRENT);
            result.vehicles.append({
                entity_type = "vehicle", id = vehicle_id, owner = GSVehicle.GetOwner(vehicle_id),
                vehicle_type = GSVehicle.GetVehicleType(vehicle_id),
                engine_type = GSVehicle.GetEngineType(vehicle_id), name = GSVehicle.GetName(vehicle_id),
                age_days = GSVehicle.GetAge(vehicle_id),
                profit_this_year = GSVehicle.GetProfitThisYear(vehicle_id),
                profit_last_year = GSVehicle.GetProfitLastYear(vehicle_id),
                state = GSVehicle.GetState(vehicle_id),
                tile = GSMap.IsValidTile(GSVehicle.GetLocation(vehicle_id)) ?
                    GSVehicle.GetLocation(vehicle_id) : null,
                in_depot = GSVehicle.IsInDepot(vehicle_id),
                current_order_index = current < 0 ? null : current
            });
            local order_count = GSOrder.GetOrderCount(vehicle_id);
            for (local index = 0; index < order_count; index++) {
                local kind = "other";
                local destination = null;
                local station = null;
                local flags = null;
                if (GSOrder.IsConditionalOrder(vehicle_id, index)) {
                    kind = "conditional";
                } else if (!GSOrder.IsVoidOrder(vehicle_id, index)) {
                    destination = GSOrder.GetOrderDestination(vehicle_id, index);
                    flags = GSOrder.GetOrderFlags(vehicle_id, index);
                    if (GSOrder.IsGotoStationOrder(vehicle_id, index)) {
                        kind = "station";
                        station = GSStation.GetStationID(destination);
                        if (!GSStation.IsValidStation(station)) station = null;
                    } else if (GSOrder.IsGotoDepotOrder(vehicle_id, index)) {
                        kind = "depot";
                    } else if (GSOrder.IsGotoWaypointOrder(vehicle_id, index)) {
                        kind = "waypoint";
                    }
                }
                result.orders.append({
                    entity_type = "order", vehicle_id = vehicle_id, index = index, kind = kind,
                    destination_tile = destination, destination_station_id = station, flags = flags
                });
            }
        }
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
        if (data == null || !data.rawin("protocol_version") ||
                (data.protocol_version != 1 && data.protocol_version != 2)) {
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
