class SimPilotGSDiscovery extends GSController {
    sequence = 0;
    instance_id = null;
    loaded = false;
    seen_commands = null;

    constructor() {
        this.seen_commands = {};
    }

    function Send(kind, correlation, company, payload) {
        this.sequence++;
        return GSAdmin.Send({
            protocol_version = 1,
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

    function Start() {
        this.instance_id = "spgd-" + GSDate.GetCurrentDate() + "-" + GSController.GetTick();
        this.Send("hello", null, null, { api_version = "15", loaded = this.loaded });
        this.Send("capabilities", null, null, {
            inbound_admin_json = true,
            outbound_admin_json = true,
            arbitrary_company_mode_candidate = true,
            reversible_probe = "set_company_name"
        });
        while (true) {
            while (GSEventController.IsEventWaiting()) {
                local event = GSEventController.GetNextEvent();
                if (event.GetEventType() == GSEvent.ET_ADMIN_PORT) {
                    this.HandleCommand(GSEventAdminPort.Convert(event).GetObject());
                }
            }
            if (GSController.GetTick() % 300 == 0) {
                this.Send("heartbeat", null, null, { tick = GSController.GetTick() });
            }
            this.Sleep(1);
        }
    }

    function HandleCommand(command) {
        if (command == null || !command.rawin("message_id") || !command.rawin("message_type")) {
            this.Send("command_rejected", "invalid", null, { error = "invalid_envelope" });
            return;
        }
        local id = command.message_id;
        if (this.seen_commands.rawin(id)) {
            this.Send("command_rejected", id, null, { error = "duplicate_request" });
            return;
        }
        this.seen_commands[id] <- true;
        if (command.message_type == "probe_company") {
            this.ProbeCompany(id, command.company_id, command.payload);
        } else if (command.message_type == "hello_request") {
            this.Send("hello", id, null, { api_version = "15", loaded = this.loaded });
            this.Send("capabilities", id, null, {
                inbound_admin_json = true,
                outbound_admin_json = true,
                arbitrary_company_mode = true,
                reversible_probe = "set_company_name"
            });
        } else if (command.message_type == "ping") {
            this.Send("command_completed", id, null, { pong = true });
        } else {
            this.Send("command_rejected", id, null, { error = "unsupported_command" });
        }
    }

    function ProbeCompany(id, company, payload) {
        if (GSCompany.ResolveCompanyID(company) == GSCompany.COMPANY_INVALID) {
            this.Send("command_rejected", id, company, { error = "invalid_company" });
            return;
        }
        local before_name = GSCompany.GetName(company);
        local before_cash = GSCompany.GetBankBalance(company);
        local before_loan = null;
        local test_success = false;
        local test_cost = null;
        local unchanged_after_test = false;
        local success = false;
        {
            local mode = GSCompanyMode(company);
            if (!GSCompanyMode.IsValid()) {
                this.Send("command_rejected", id, company, { error = "invalid_company_mode" });
                return;
            }
            before_loan = GSCompany.GetLoanAmount();
            if (payload.rawin("temporary_name")) {
                {
                    local accounting = GSAccounting();
                    local test_mode = GSTestMode();
                    test_success = GSCompany.SetName(payload.temporary_name);
                    test_cost = accounting.GetCosts();
                }
                unchanged_after_test = GSCompany.GetName(company) == before_name;
                success = GSCompany.SetName(payload.temporary_name);
                if (success) GSCompany.SetName(before_name);
            }
        }
        this.Send("command_completed", id, company, {
            company_mode_valid = true,
            before_name = before_name,
            before_cash = before_cash,
            before_loan = before_loan,
            test_mode_success = test_success,
            test_mode_cost = test_cost,
            unchanged_after_test = unchanged_after_test,
            reversible_name_change = success,
            restored_name = GSCompany.GetName(company)
        });
    }

    function Save() {
        return { sequence = this.sequence, seen_commands = this.seen_commands };
    }

    function Load(version, data) {
        this.loaded = true;
        if (data != null && data.rawin("sequence")) this.sequence = data.sequence;
        if (data != null && data.rawin("seen_commands")) this.seen_commands = data.seen_commands;
    }
}
