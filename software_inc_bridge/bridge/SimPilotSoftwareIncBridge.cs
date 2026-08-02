using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Threading;
using SimPilot.GameBridge;
using UnityEngine;
using UnityEngine.UI;

namespace SimPilotSoftwareIncBridge
{
    public sealed class SimPilotBridgeMeta : ModMeta
    {
        // Software Inc. requires this documented opt-in for compiled mods that use
        // loopback networking and read the private authentication token.
        public static bool GiveMeFreedom = true;

        public override string Name { get { return "Sim Pilot Read-Only Bridge"; } }

        public override void ConstructOptionsScreen(RectTransform parent, bool inGame) { }
    }

    public sealed class SimPilotBridgeBehaviour : ModBehaviour
    {
        private SoftwareIncStateProvider? provider;
        private BridgeServer? server;
        private SimPilotCapturePump? capturePump;

        public override void OnActivate()
        {
            var token = File.ReadAllText(TokenPath()).Trim();
            var nextProvider = new SoftwareIncStateProvider(Thread.CurrentThread.ManagedThreadId);
            var pumpObject = new GameObject("Sim Pilot Capture Pump");
            DontDestroyOnLoad(pumpObject);
            var nextPump = pumpObject.AddComponent<SimPilotCapturePump>();
            nextPump.Initialize(nextProvider);
            var nextServer = new BridgeServer(token, nextProvider,
                SoftwareIncBridgeContract.Descriptor.DefaultPort,
                SoftwareIncBridgeContract.Descriptor,
                message => Debug.LogError("SIM_PILOT_SOFTWARE_INC_BRIDGE " + message));
            nextServer.Start();
            provider = nextProvider;
            server = nextServer;
            capturePump = nextPump;
            GameSettings.GameReady += OnGameReady;
            Debug.Log("SIM_PILOT_SOFTWARE_INC_BRIDGE schema=1 event=activated authority=read_only_loopback");
        }

        public override void OnDeactivate()
        {
            GameSettings.GameReady -= OnGameReady;
            if (server != null) server.Dispose();
            if (provider != null) provider.Dispose();
            if (capturePump != null) Destroy(capturePump.gameObject);
            Debug.Log("SIM_PILOT_SOFTWARE_INC_BRIDGE schema=1 event=deactivated");
        }

        private void OnGameReady(object sender, EventArgs eventArgs)
        {
            if (provider != null) provider.BeginGameSession();
            Debug.Log("SIM_PILOT_SOFTWARE_INC_BRIDGE schema=1 event=game_ready thread=" +
                Thread.CurrentThread.ManagedThreadId.ToString(CultureInfo.InvariantCulture));
        }

        private static string TokenPath()
        {
            // Unity 2018 Mono maps ApplicationData to ~/.config on macOS, unlike
            // native Python. The selected adapter is macOS-only, so anchor this
            // owner-only token to the proven macOS user-data location explicitly.
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Personal),
                "Library", "Application Support", "Sim Pilot", "software-inc", "bridge",
                "auth-token");
        }
    }

    public sealed class SimPilotCapturePump : MonoBehaviour
    {
        private SoftwareIncStateProvider? provider;

        internal void Initialize(SoftwareIncStateProvider stateProvider)
        {
            provider = stateProvider ?? throw new ArgumentNullException(nameof(stateProvider));
            enabled = true;
        }

        private void Start()
        {
            Debug.Log("SIM_PILOT_SOFTWARE_INC_BRIDGE schema=1 event=pump_started thread=" +
                Thread.CurrentThread.ManagedThreadId.ToString(CultureInfo.InvariantCulture));
        }

        private void Update()
        {
            if (provider != null) provider.ProcessPendingCapture();
        }
    }

    internal static class SoftwareIncBridgeContract
    {
        public static readonly BridgeContractDescriptor Descriptor = new BridgeContractDescriptor(
            3, "software-inc-readonly-v10", "software-inc", "1.8.41", 1048576, 18462,
            "Sim Pilot Software Inc bridge",
            new[] { "applicants", "build_catalog", "build_ui", "company", "contract_market", "contract_results", "contract_ui", "education", "education_ui", "employees", "finances", "game_state", "infrastructure", "office_ui", "offices", "product_catalog", "product_ui", "products", "staffing_ui", "teams", "work_items" });
    }

    internal sealed class CaptureRequest : IDisposable
    {
        public readonly ManualResetEvent Completed = new ManualResetEvent(false);
        public RuntimeSnapshot? Snapshot;
        public Exception? Error;
        public volatile bool Cancelled;
        public void Dispose() { Completed.Dispose(); }
    }

    internal sealed class SoftwareIncStateProvider : IReadOnlyGameStateProvider, IDisposable
    {
        private readonly int mainThreadId;
        private readonly object gate = new object();
        private CaptureRequest? pending;
        private volatile bool disposed;
        private string gameSessionId = "menu-" + Guid.NewGuid().ToString("D");

        public SoftwareIncStateProvider(int mainThreadId) { this.mainThreadId = mainThreadId; }

        public void BeginGameSession()
        {
            AssertMainThread();
            gameSessionId = Guid.NewGuid().ToString("D");
        }

        public RuntimeSnapshot Capture()
        {
            if (Thread.CurrentThread.ManagedThreadId == mainThreadId) return CaptureOnMainThread();
            if (disposed) throw new ObjectDisposedException(nameof(SoftwareIncStateProvider));
            using (var request = new CaptureRequest())
            {
                lock (gate)
                {
                    if (pending != null)
                        throw new InvalidOperationException("a main-thread capture is already pending");
                    pending = request;
                }
                if (!request.Completed.WaitOne(TimeSpan.FromSeconds(3)))
                {
                    request.Cancelled = true;
                    lock (gate) { if (ReferenceEquals(pending, request)) pending = null; }
                    throw new TimeoutException("Software Inc main-thread snapshot timed out");
                }
                if (request.Error != null) throw new InvalidOperationException("main-thread snapshot failed", request.Error);
                return request.Snapshot ?? throw new InvalidOperationException("main-thread snapshot returned no state");
            }
        }

        public void Dispose()
        {
            disposed = true;
            lock (gate)
            {
                if (pending == null) return;
                pending.Error = new ObjectDisposedException(nameof(SoftwareIncStateProvider));
                pending.Completed.Set();
                pending = null;
            }
        }

        public void ProcessPendingCapture()
        {
            AssertMainThread();
            CaptureRequest? request;
            lock (gate) { request = pending; pending = null; }
            if (request == null || request.Cancelled) return;
            try
            {
                if (disposed) throw new ObjectDisposedException(nameof(SoftwareIncStateProvider));
                request.Snapshot = CaptureOnMainThread();
            }
            catch (Exception error)
            {
                request.Error = error;
                Debug.LogError("SIM_PILOT_SOFTWARE_INC_BRIDGE main-thread capture failed: " + error);
            }
            finally
            {
                request.Completed.Set();
            }
        }

        private RuntimeSnapshot CaptureOnMainThread()
        {
            AssertMainThread();
            var settings = GameSettings.Instance;
            if (settings == null || settings.MyCompany == null)
                return Unavailable("a playable company is not loaded");
            var company = settings.MyCompany;
            var surfaces = new List<ObservationSurfaceState>();
            surfaces.Add(CompanySurface(company));
            surfaces.Add(FinanceSurface(company));
            surfaces.Add(TeamSurface(settings));
            surfaces.Add(EmployeeSurface(settings));
            surfaces.Add(ApplicantSurface());
            surfaces.Add(StaffingUiSurface());
            surfaces.Add(OfficeSurface(settings));
            surfaces.Add(InfrastructureSurface(settings));
            surfaces.Add(OfficeUiSurface());
            surfaces.Add(BuildCatalogSurface());
            surfaces.Add(BuildUiSurface(settings));
            surfaces.Add(ContractMarketSurface());
            surfaces.Add(ContractResultSurface());
            surfaces.Add(ContractUiSurface());
            surfaces.Add(EducationSurface(settings));
            surfaces.Add(EducationUiSurface());
            surfaces.Add(WorkItemSurface(company));
            surfaces.Add(ProductCatalogSurface());
            surfaces.Add(ProductUiSurface());
            surfaces.Add(ProductSurface(company));
            var saveName = settings.AssociatedSave == null ? null : settings.AssociatedSave.UniqueName;
            return new RuntimeSnapshot
            {
                GameVersion = "1.8.41",
                Platform = "macos",
                Architecture = "x86_64",
                GameSessionId = gameSessionId,
                MapIdentity = Identity.Unavailable("Software Inc. does not expose a map identity through the proven public API"),
                SaveIdentity = string.IsNullOrWhiteSpace(saveName)
                    ? Identity.Unavailable("no associated save name is exposed")
                    : Identity.Observed(saveName!, saveName, "GameSettings.AssociatedSave.UniqueName"),
                GameStateAvailable = true,
                GameStateDetail = "captured on Unity main thread from public Software Inc. APIs",
                GameStateValues = new Dictionary<string, JsonValue>
                {
                    ["current_time"] = JsonValue.String(TimeOfDay.Instance.GetDate().ToString()),
                    ["days_per_month"] = JsonValue.Integer(GameSettings.DaysPerMonth),
                    ["force_pause"] = JsonValue.Boolean(GameSettings.ForcePause),
                    ["game_mode"] = JsonValue.String(settings.CampaignMode ? "campaign" : settings.EditMode ? "editor" : "sandbox"),
                    ["simulation_speed"] = JsonValue.String(GameSettings.GameSpeed.ToString(CultureInfo.InvariantCulture)),
                },
                SemanticSurfaces = surfaces,
                Limitations = new[] { "read-only bridge; gameplay action catalog is empty", "available contracts are observable only while the visible Contracts window is open", "product configuration and operating-system choices are observable only while the visible design window is open", "furniture recurring utility cost is not projected" },
            };
        }

        private RuntimeSnapshot Unavailable(string detail)
        {
            return new RuntimeSnapshot
            {
                GameVersion = "1.8.41",
                Platform = "macos",
                Architecture = "x86_64",
                GameSessionId = gameSessionId,
                GameStateAvailable = false,
                GameStateDetail = detail,
                MapIdentity = Identity.Unavailable("map identity unavailable"),
                SaveIdentity = Identity.Unavailable("save identity unavailable"),
                SemanticSurfaces = new[]
                {
                    ObservationSurfaceState.Unavailable("company", detail),
                    ObservationSurfaceState.Unavailable("contract_market", detail),
                    ObservationSurfaceState.Unavailable("contract_results", detail),
                    ObservationSurfaceState.Unavailable("contract_ui", detail),
                    ObservationSurfaceState.Unavailable("education", detail),
                    ObservationSurfaceState.Unavailable("education_ui", detail),
                    ObservationSurfaceState.Unavailable("applicants", detail),
                    ObservationSurfaceState.Unavailable("build_catalog", detail),
                    ObservationSurfaceState.Unavailable("build_ui", detail),
                    ObservationSurfaceState.Unavailable("employees", detail),
                    ObservationSurfaceState.Unavailable("finances", detail),
                    ObservationSurfaceState.Unavailable("infrastructure", detail),
                    ObservationSurfaceState.Unavailable("office_ui", detail),
                    ObservationSurfaceState.Unavailable("offices", detail),
                    ObservationSurfaceState.Unavailable("product_catalog", detail),
                    ObservationSurfaceState.Unavailable("product_ui", detail),
                    ObservationSurfaceState.Unavailable("products", detail),
                    ObservationSurfaceState.Unavailable("staffing_ui", detail),
                    ObservationSurfaceState.Unavailable("teams", detail),
                    ObservationSurfaceState.Unavailable("work_items", detail),
                },
                Limitations = new[] { "read-only bridge; gameplay action catalog is empty" },
            };
        }

        private static ObservationSurfaceState CompanySurface(Company company)
        {
            return Surface("company", CoverageStatus.ObservedComplete,
                new[] { "business_reputation", "fans", "founded", "name" }, "public Company API",
                Entity("company", company.ID.ToString(CultureInfo.InvariantCulture), new Dictionary<string, JsonValue>
                {
                    ["business_reputation"] = JsonValue.Number(company.BusinessReputation),
                    ["fans"] = JsonValue.Integer(company.Fans),
                    ["founded"] = JsonValue.String(company.Founded.ToString()),
                    ["name"] = JsonValue.String(company.Name),
                }));
        }

        private static ObservationSurfaceState FinanceSurface(Company company)
        {
            return Surface("finances", CoverageStatus.ObservedPartial,
                new[] { "cash", "valuation" }, "current public Company totals; detailed ledger is not covered",
                Entity("company_finances", company.ID.ToString(CultureInfo.InvariantCulture), new Dictionary<string, JsonValue>
                {
                    ["cash"] = JsonValue.Number(company.Money),
                    ["valuation"] = JsonValue.Number(company.Valuation),
                }));
        }

        private static ObservationSurfaceState TeamSurface(GameSettings settings)
        {
            var entities = new List<ObservedEntityState>();
            foreach (var pair in settings.sActorManager.Teams)
            {
                var team = pair.Value;
                entities.Add(Entity("team", pair.Key, new Dictionary<string, JsonValue>
                {
                    ["cohesion"] = JsonValue.Number(team.Cohesion),
                    ["compatibility"] = JsonValue.Number(team.Compatibility),
                    ["employee_count"] = JsonValue.Integer(team.Count),
                    ["name"] = JsonValue.String(team.Name),
                    ["work_end"] = JsonValue.Number(team.WorkEnd),
                    ["work_start"] = JsonValue.Number(team.WorkStart),
                }));
            }
            entities.Sort(EntityCompare);
            return Surface("teams", CoverageStatus.ObservedComplete,
                new[] { "cohesion", "compatibility", "employee_count", "name", "work_end", "work_start" },
                "all teams from ActorManager.Teams", entities.ToArray());
        }

        private static ObservationSurfaceState EmployeeSurface(GameSettings settings)
        {
            var entities = new List<ObservedEntityState>();
            foreach (var actor in settings.sActorManager.Actors)
            {
                var employee = actor.employee;
                if (employee == null || employee.MyEmployer != settings.MyCompany) continue;
                entities.Add(Entity("employee", employee.NetworkID.ToString(CultureInfo.InvariantCulture),
                    new Dictionary<string, JsonValue>
                    {
                        ["dismissed"] = JsonValue.Boolean(employee.Dismissed),
                        ["founder"] = JsonValue.Boolean(employee.Founder),
                        ["job_satisfaction"] = JsonValue.Number(employee.JobSatisfaction),
                        ["name"] = JsonValue.String(employee.FullName),
                        ["role"] = JsonValue.String(employee.RoleString),
                        ["salary"] = JsonValue.Number(employee.Salary),
                        ["skill_artist"] = JsonValue.Number(employee.GetSkillI(3)),
                        ["skill_designer"] = JsonValue.Number(employee.GetSkillI(2)),
                        ["skill_lead"] = JsonValue.Number(employee.GetSkillI(0)),
                        ["skill_programmer"] = JsonValue.Number(employee.GetSkillI(1)),
                        ["skill_service"] = JsonValue.Number(employee.GetSkillI(4)),
                        ["taking_courses"] = JsonValue.Boolean(actor.TakingCourses),
                        ["courses"] = JsonValue.String(CourseList(actor)),
                        ["last_course"] = JsonValue.String(actor.LastCourse.ToString()),
                        ["team"] = JsonValue.String(actor.Team ?? string.Empty),
                    }));
            }
            entities.Sort(EntityCompare);
            return Surface("employees", CoverageStatus.ObservedComplete,
                new[] { "courses", "dismissed", "founder", "job_satisfaction", "last_course", "name", "role", "salary", "skill_artist", "skill_designer", "skill_lead", "skill_programmer", "skill_service", "taking_courses", "team" },
                "all employed actors from ActorManager.Actors", entities.ToArray());
        }

        private static string CourseList(Actor actor)
        {
            if (actor.Courses == null) return string.Empty;
            var courses = new List<string>();
            foreach (var course in actor.Courses)
                courses.Add(course.Key.ToString() + ":" + (course.Value ?? string.Empty));
            courses.Sort(StringComparer.Ordinal);
            return string.Join("|", courses.ToArray());
        }

        private static ObservationSurfaceState EducationSurface(GameSettings settings)
        {
            var entities = new List<ObservedEntityState>();
            entities.Add(Entity("education_rule", "current", new Dictionary<string, JsonValue>
            {
                ["duration_months"] = JsonValue.Integer(EducationWindow.EducationMonths),
            }));
            foreach (var actor in settings.sActorManager.Actors)
            {
                var employee = actor.employee;
                if (employee == null || employee.MyEmployer != settings.MyCompany) continue;
                var specializations = employee.GetAllSpecializations();
                if (specializations == null) continue;
                for (var roleIndex = 0; roleIndex < specializations.Length; roleIndex++)
                {
                    var roleSpecs = specializations[roleIndex];
                    if (roleSpecs == null) continue;
                    foreach (var pair in roleSpecs)
                    {
                        var role = (Employee.EmployeeRole)roleIndex;
                        entities.Add(Entity("employee_specialization",
                            employee.NetworkID.ToString(CultureInfo.InvariantCulture) + ":" +
                            role.ToString() + ":" + pair.Key,
                            new Dictionary<string, JsonValue>
                            {
                                ["employee_id"] = JsonValue.String(employee.NetworkID.ToString(CultureInfo.InvariantCulture)),
                                ["employee_name"] = JsonValue.String(employee.FullName),
                                ["level"] = JsonValue.Integer(pair.Value),
                                ["one_time_cost"] = JsonValue.Number(EducationWindow.GetEducationCost(pair.Value)),
                                ["role"] = JsonValue.String(role.ToString()),
                                ["specialization"] = JsonValue.String(pair.Key),
                                ["team"] = JsonValue.String(actor.Team ?? string.Empty),
                            }));
                    }
                }
            }
            entities.Sort(EntityCompare);
            return Surface("education", CoverageStatus.ObservedComplete,
                new[] { "duration_months", "employee_id", "employee_name", "level", "one_time_cost", "role", "specialization", "team" },
                "current education duration and every employed actor specialization from public APIs; no education method is invoked",
                entities.ToArray());
        }

        private static ObservationSurfaceState ContractMarketSurface()
        {
            var window = SingleActive<ContractWindow>();
            if (window == null)
                return ObservationSurfaceState.Unavailable("contract_market",
                    "the visible Contracts window is not open");
            if (window.Contracts == null || window.Contracts.ActualItems == null)
                return FailedSurface("contract_market", "the active Contracts window has no available list");
            var entities = new List<ObservedEntityState>();
            var identities = new HashSet<string>(StringComparer.Ordinal);
            for (var index = 0; index < window.Contracts.ActualItems.Count; index++)
            {
                var work = window.Contracts.ActualItems[index] as ContractWork;
                if (work == null) continue;
                if (!identities.Add(ContractIdentity(work)))
                    return FailedSurface("contract_market",
                        "the visible contract list contains duplicate stable identities");
                entities.Add(ContractEntity(work, index));
            }
            entities.Sort(EntityCompare);
            return Surface("contract_market", CoverageStatus.ObservedComplete,
                new[] { "added", "art_ratio", "client", "deadline", "days_remaining", "dev_time", "difficulty", "display_index", "features", "minimum_progress", "months", "name", "penalty", "per_bug_penalty", "quality_target", "reward", "software_category", "software_type", "status" },
                "all available ContractWork rows from the visible ContractWindow; no selection or callback is invoked",
                entities.ToArray());
        }

        private static ObservedEntityState ContractEntity(ContractWork work, int index)
        {
            var features = new List<string>();
            if (work.Features != null)
                foreach (var feature in work.Features)
                    if (feature != null) features.Add(feature.GetLocalizedName());
            features.Sort(StringComparer.Ordinal);
            var now = TimeOfDay.Instance.GetDate();
            var completionWindowDays = work.Months * GameSettings.DaysPerMonth;
            var monthLabel = work.Months == 1 ? "month" : "months";
            var dayLabel = completionWindowDays == 1 ? "day" : "days";
            var relativeDeadline = string.Format(
                CultureInfo.InvariantCulture,
                "{0} in-game {1} after work starts ({2} in-game {3})",
                work.Months,
                monthLabel,
                completionWindowDays,
                dayLabel);
            var identity = ContractIdentity(work);
            return Entity("available_contract", identity, new Dictionary<string, JsonValue>
            {
                ["added"] = JsonValue.String(work.Added.ToString()),
                ["art_ratio"] = JsonValue.Number(work.Art),
                ["client"] = JsonValue.String(work.Company ?? string.Empty),
                // ContractWork.Deadline is the default SDateTime until the contract starts.
                // The available list exposes the actual pre-acceptance commitment as Months.
                ["deadline"] = JsonValue.String(relativeDeadline),
                ["days_remaining"] = JsonValue.Number(completionWindowDays),
                ["dev_time"] = JsonValue.Number(work.GetDevTime()),
                ["difficulty"] = JsonValue.Number(work.Difficulty),
                ["display_index"] = JsonValue.Integer(index),
                ["features"] = JsonValue.String(string.Join("|", features.ToArray())),
                ["minimum_progress"] = JsonValue.Number(work.MinProg),
                ["months"] = JsonValue.Integer(work.Months),
                ["name"] = JsonValue.String(work.GetName()),
                ["penalty"] = JsonValue.Number(work.Penalty),
                ["per_bug_penalty"] = JsonValue.Number(work.PerBug),
                ["quality_target"] = JsonValue.Number(work.Quality),
                ["reward"] = JsonValue.Number(work.GetIncome()),
                ["software_category"] = JsonValue.String(work.SoftwareCat == null ? string.Empty : work.SoftwareCat.ToString()),
                ["software_type"] = JsonValue.String(work.SoftwareType == null ? string.Empty : work.SoftwareType.ToString()),
                ["status"] = JsonValue.String(work.GetStatus(now)),
            });
        }

        private static ObservationSurfaceState ContractResultSurface()
        {
            var hud = HUD.Instance;
            var window = hud != null ? hud.contractWindow : null;
            if (window == null || window.ContractResults == null || window.ContractResults.ActualItems == null)
                return ObservationSurfaceState.Unavailable("contract_results",
                    "the initialized contract result list is unavailable");
            var entities = new List<ObservedEntityState>();
            for (var index = 0; index < window.ContractResults.ActualItems.Count; index++)
            {
                var result = window.ContractResults.ActualItems[index] as ContractResult;
                if (result == null || result.Contract == null) continue;
                entities.Add(Entity("contract_result",
                    ContractIdentity(result.Contract) + ":" + index.ToString(CultureInfo.InvariantCulture),
                    new Dictionary<string, JsonValue>
                    {
                        ["actual_month"] = JsonValue.Integer(result.ActualMonth),
                        ["bug_penalty"] = JsonValue.Number(result.BugPenalty),
                        ["bugs"] = JsonValue.Integer(result.Bugs),
                        ["client"] = JsonValue.String(result.Contract.Company ?? string.Empty),
                        ["completed_at"] = JsonValue.String(result.Date.ToString()),
                        ["final_result"] = JsonValue.Number(result.FinalResult),
                        ["income"] = JsonValue.Number(result.Income),
                        ["late_penalty"] = JsonValue.Number(result.LatePenalty),
                        ["name"] = JsonValue.String(result.Contract.GetName()),
                        ["quality_penalty"] = JsonValue.Number(result.QualityPenalty),
                        ["quality_result"] = JsonValue.Number(result.QualityResult),
                        ["reputation_change"] = JsonValue.Number(result.GetRep()),
                        ["status"] = JsonValue.String(result.Status.ToString()),
                    }));
            }
            entities.Sort(EntityCompare);
            return Surface("contract_results", CoverageStatus.ObservedComplete,
                new[] { "actual_month", "bug_penalty", "bugs", "client", "completed_at", "final_result", "income", "late_penalty", "name", "quality_penalty", "quality_result", "reputation_change", "status" },
                "completed contract results from the initialized ContractWindow public list",
                entities.ToArray());
        }

        private static ObservationSurfaceState WorkItemSurface(Company company)
        {
            var entities = new List<ObservedEntityState>();
            foreach (var item in company.WorkItems)
            {
                if (item == null) continue;
                var contractDeadline = item.contract == null
                    ? string.Empty
                    : item.contract.Deadline.ToString() ?? string.Empty;
                var contractDaysRemaining = item.contract == null
                    ? 0f
                    : SDateTime.GetDays(TimeOfDay.Instance.GetDate(), item.contract.Deadline);
                var contractDeadlineObserved = item.contract != null
                    && contractDaysRemaining >= 0f
                    && contractDeadline.IndexOf("1900", StringComparison.Ordinal) < 0;
                if (!contractDeadlineObserved)
                {
                    // Software Inc. leaves ContractWork.Deadline at its 1900 sentinel in some
                    // accepted-work lifecycles. Never expose that sentinel as a real deadline.
                    contractDeadline = string.Empty;
                    contractDaysRemaining = 0f;
                }
                var values = new Dictionary<string, JsonValue>
                {
                    ["assigned_teams"] = SafeString(item.DevTeams == null ? string.Empty : string.Join("|", item.DevTeams)),
                    ["category"] = SafeString(item.GetCategory()),
                    ["contract_client"] = SafeString(item.contract == null ? string.Empty : item.contract.Company),
                    ["contract_deadline"] = SafeString(contractDeadline),
                    ["contract_deadline_observed"] = JsonValue.Boolean(contractDeadlineObserved),
                    ["contract_days_remaining"] = JsonValue.Number(contractDaysRemaining),
                    ["contract_identity"] = SafeString(item.contract == null ? string.Empty : ContractIdentity(item.contract)),
                    ["contract_name"] = SafeString(item.contract == null ? string.Empty : item.contract.GetName()),
                    ["contract_penalty"] = JsonValue.Number(item.contract == null ? 0f : item.contract.Penalty),
                    ["contract_reward"] = JsonValue.Number(item.contract == null ? 0f : item.contract.GetIncome()),
                    ["done"] = JsonValue.Boolean(item.Done),
                    ["employee_count"] = JsonValue.Integer(item.GetEmployeeCount()),
                    ["enabled"] = JsonValue.Boolean(item.Enabled),
                    ["is_contract"] = JsonValue.Boolean(item.contract != null),
                    ["name"] = SafeString(item.Name),
                    ["paused"] = JsonValue.Boolean(item.Paused),
                    ["progress"] = JsonValue.Number(item.GetProgress()),
                    ["progress_label"] = SafeString(item.GetProgressLabel()),
                    ["stage"] = SafeString(item.GetCurrentStage()),
                    ["work_type"] = SafeString(item.GetWorkTypeName()),
                };
                var design = item as DesignDocument;
                if (design != null)
                {
                    values["contract_started"] = JsonValue.Boolean(design.ContractStarted);
                    values["has_finished"] = JsonValue.Boolean(design.HasFinished);
                    values["iteration"] = JsonValue.Integer(design.Iteration);
                    values["lead_designer"] = JsonValue.String(design.LeadDesigner == null ? string.Empty : design.LeadDesigner.FullName);
                    values["minimum_progress"] = JsonValue.Number(design.contract == null ? 0f : design.contract.MinProg);
                    values["review_accuracy"] = JsonValue.Number(design.ReviewAccuracy);
                }
                var alpha = item as SoftwareAlpha;
                if (alpha != null)
                {
                    values["bugs"] = JsonValue.Number(alpha.Bugs);
                    values["fixed_bugs"] = JsonValue.Number(alpha.FixedBugs);
                    values["has_finished"] = JsonValue.Boolean(alpha.HasFinished);
                    values["has_finished_art"] = JsonValue.Boolean(alpha.HasFinishedArt);
                    values["has_finished_code"] = JsonValue.Boolean(alpha.HasFinishedCode);
                    values["in_beta"] = JsonValue.Boolean(alpha.InBeta);
                    values["quality"] = JsonValue.Number(alpha.GetQuality());
                    values["released"] = JsonValue.Boolean(alpha.Released);
                    values["reviews_done"] = JsonValue.Integer(alpha.ReviewsDone);
                    values["review_score"] = JsonValue.Number(alpha.ReviewScore);
                }
                var review = item as ReviewWork;
                if (review != null)
                {
                    values["review_company"] = JsonValue.String(review.ReviewCompany ?? string.Empty);
                    values["review_cost_per_review"] = JsonValue.Number(review.CostPerReview);
                    values["review_optimal_count"] = JsonValue.Integer(review.OptimalReviews);
                    values["review_target_work_item_id"] = JsonValue.String(
                        review.TargetWork == null
                            ? string.Empty
                            : review.TargetWork.ID.ToString(CultureInfo.InvariantCulture));
                    values["reviewer_count"] = JsonValue.Integer(review.Reviewers);
                    values["reviews_requested"] = JsonValue.Integer(review.Reviews);
                }
                entities.Add(Entity("work_item", item.ID.ToString(CultureInfo.InvariantCulture), values));
            }
            entities.Sort(EntityCompare);
            return Surface("work_items", CoverageStatus.ObservedComplete,
                new[] { "assigned_teams", "bugs", "category", "contract_client", "contract_days_remaining", "contract_deadline", "contract_deadline_observed", "contract_identity", "contract_name", "contract_penalty", "contract_reward", "contract_started", "done", "employee_count", "enabled", "fixed_bugs", "has_finished", "has_finished_art", "has_finished_code", "in_beta", "is_contract", "iteration", "lead_designer", "minimum_progress", "name", "paused", "progress", "progress_label", "quality", "released", "review_accuracy", "review_company", "review_cost_per_review", "review_optimal_count", "review_score", "review_target_work_item_id", "reviewer_count", "reviews_done", "reviews_requested", "stage", "work_type" },
                "all company work items with complete public lifecycle state; contract linkage is explicit",
                entities.ToArray());
        }

        private static ObservationSurfaceState ProductCatalogSurface()
        {
            var entities = new List<ObservedEntityState>();
            var year = TimeOfDay.Instance.GetDate().RealYear;
            var names = new List<string>(GameData.SoftwareTypeNames());
            names.Sort(StringComparer.Ordinal);
            foreach (var name in names)
            {
                var type = GameData.GetSoftwareType(name);
                if (type == null) continue;
                var categories = new List<string>();
                foreach (var pair in type.Categories)
                {
                    var category = pair.Value;
                    if (category == null) continue;
                    categories.Add(category.Name);
                    entities.Add(Entity("software_category", type.Name + ":" + category.Name,
                        new Dictionary<string, JsonValue>
                        {
                            ["description"] = SafeString(category.Description),
                            ["hidden"] = JsonValue.Boolean(category.Hidden),
                            ["ideal_price"] = JsonValue.Number(category.IdealPrice),
                            ["is_default"] = JsonValue.Boolean(category.IsDefault),
                            ["is_hardware"] = JsonValue.Boolean(category.IsHardware()),
                            ["name"] = SafeString(category.Name),
                            ["product_type"] = SafeString(type.Name),
                            ["unlocked"] = JsonValue.Boolean(category.IsUnlocked(year)),
                        }));
                    var needs = type.GetNeeds(category.Name) ?? new string[0];
                    Array.Sort(needs, StringComparer.Ordinal);
                    foreach (var need in needs)
                        entities.Add(Entity("product_prerequisite",
                            type.Name + ":" + category.Name + ":" + need,
                            new Dictionary<string, JsonValue>
                            {
                                ["category"] = SafeString(category.Name),
                                ["product_type"] = SafeString(type.Name),
                                ["required_product_type"] = SafeString(need),
                            }));
                }
                categories.Sort(StringComparer.Ordinal);
                entities.Add(Entity("software_type", type.Name,
                    new Dictionary<string, JsonValue>
                    {
                        ["categories"] = JsonValue.String(string.Join("|", categories.ToArray())),
                        ["description"] = SafeString(type.Description),
                        ["in_house"] = JsonValue.Boolean(type.InHouse),
                        ["name"] = SafeString(type.Name),
                        ["one_client"] = JsonValue.Boolean(type.OneClient),
                        ["optimal_development_time"] = JsonValue.Number(type.OptimalDevTime),
                        ["os_specific"] = JsonValue.Boolean(type.OSSpecific),
                        ["unlocked"] = JsonValue.Boolean(type.IsUnlocked(year)),
                    }));
                foreach (var pair in type.Features)
                {
                    var feature = pair.Value;
                    if (feature == null) continue;
                    var dependencies = new string[0];
                    var specFeature = feature as SpecFeature;
                    if (specFeature != null && specFeature.Dependencies != null)
                    {
                        dependencies = (string[])specFeature.Dependencies.Clone();
                        Array.Sort(dependencies, StringComparer.Ordinal);
                    }
                    entities.Add(Entity("software_feature", type.Name + ":" + feature.Name,
                        new Dictionary<string, JsonValue>
                        {
                            ["code_art_ratio"] = JsonValue.Number(feature.CodeArtRatio),
                            ["dependencies"] = JsonValue.String(string.Join("|", dependencies)),
                            ["development_time"] = JsonValue.Number(feature.DevTime),
                            ["localized_name"] = SafeString(feature.GetLocalizedName()),
                            ["name"] = SafeString(feature.Name),
                            ["product_type"] = SafeString(type.Name),
                            ["server_requirement"] = JsonValue.Number(feature.ServerRequirement),
                            ["specialization"] = SafeString(feature.Spec),
                            ["unlocked"] = JsonValue.Boolean(feature.IsUnlocked(year)),
                        }));
                }
            }
            entities.Sort(EntityCompare);
            return Surface("product_catalog", CoverageStatus.ObservedComplete,
                new[] { "categories", "category", "code_art_ratio", "dependencies", "description", "development_time", "hidden", "ideal_price", "in_house", "is_default", "is_hardware", "localized_name", "name", "one_client", "optimal_development_time", "os_specific", "product_type", "required_product_type", "server_requirement", "specialization", "unlocked" },
                "all current Software Inc. 1.8.41 software types, categories, features, and declared prerequisites from the public GameData and SoftwareType APIs",
                entities.ToArray());
        }

        private static ObservationSurfaceState ProductSurface(Company company)
        {
            var entities = new List<ObservedEntityState>();
            foreach (var product in company.Products)
            {
                if (product == null) continue;
                var features = new List<string>();
                if (product.Features != null)
                    foreach (var feature in product.Features)
                        if (feature != null) features.Add(feature.GetLocalizedName());
                features.Sort(StringComparer.Ordinal);
                var operatingSystems = new List<string>();
                if (product._oss != null)
                    foreach (var identity in product._oss)
                        operatingSystems.Add(identity.ToString(CultureInfo.InvariantCulture));
                operatingSystems.Sort(StringComparer.Ordinal);
                entities.Add(Entity("product", product.ID.ToString(CultureInfo.InvariantCulture),
                    new Dictionary<string, JsonValue>
                    {
                        ["archived"] = JsonValue.Boolean(product.Archived),
                        ["bugs"] = JsonValue.Integer(product.Bugss),
                        ["category"] = SafeString(product.Category == null ? string.Empty : product.Category.Name),
                        ["code_progress"] = JsonValue.Number(product.CodeProgress),
                        ["code_quality"] = JsonValue.Number(product.CodeQuality),
                        ["development_started"] = SafeString(product.DevStart.ToString()),
                        ["development_time"] = JsonValue.Number(product.DevTime),
                        ["features"] = JsonValue.String(string.Join("|", features.ToArray())),
                        ["name"] = SafeString(product.Name),
                        ["operating_system_ids"] = JsonValue.String(string.Join("|", operatingSystems.ToArray())),
                        ["price"] = JsonValue.Number(product.Price),
                        ["release_date"] = SafeString(product.Release.ToString()),
                        ["review_score"] = JsonValue.Number(product.ReviewScore),
                        ["sales"] = JsonValue.Integer(product.UnitSum),
                        ["server"] = SafeString(product.Server),
                        ["type"] = SafeString(product.Type == null ? string.Empty : product.Type.Name),
                        ["userbase"] = JsonValue.Integer(product.Userbase),
                    }));
            }
            entities.Sort(EntityCompare);
            return Surface("products", CoverageStatus.ObservedComplete,
                new[] { "archived", "bugs", "category", "code_progress", "code_quality", "development_started", "development_time", "features", "name", "operating_system_ids", "price", "release_date", "review_score", "sales", "server", "type", "userbase" },
                "all released company products from Company.Products; unreleased lifecycle work remains in work_items",
                entities.ToArray());
        }

        private static ObservationSurfaceState ProductUiSurface()
        {
            var hud = HUD.Instance;
            var window = hud != null ? hud.docWindow : null;
            var windowActive = window != null && Active(window.Window);
            var teamSelect = hud != null ? hud.TeamSelectWindow : null;
            var teamSelectActive = windowActive && teamSelect != null && Active(teamSelect.Window);
            var entities = new List<ObservedEntityState>();
            var observedPaths = new HashSet<string>(StringComparer.Ordinal);
            var scene = teamSelectActive ? "product_team_selection"
                : windowActive ? "product_configuration" : "gameplay";
            var selectedFeatures = new List<string>();
            var selectedOperatingSystems = new List<string>();
            var availableOperatingSystems = new List<string>();
            if (windowActive && window != null)
            {
                foreach (var feature in window.GetFeatures())
                    if (feature != null) selectedFeatures.Add(feature.GetLocalizedName());
                foreach (var product in window.GetOSs())
                    if (product != null) selectedOperatingSystems.Add(ProductIdentity(product));
                if (window.OSList != null && window.OSList.ActualItems != null)
                    foreach (var item in window.OSList.ActualItems)
                    {
                        var product = item as SoftwareProduct;
                        if (product != null) availableOperatingSystems.Add(ProductIdentity(product));
                    }
            }
            selectedFeatures.Sort(StringComparer.Ordinal);
            selectedOperatingSystems.Sort(StringComparer.Ordinal);
            availableOperatingSystems.Sort(StringComparer.Ordinal);
            entities.Add(Entity("product_ui_state", "current", new Dictionary<string, JsonValue>
            {
                ["available_operating_systems"] = JsonValue.String(string.Join("|", availableOperatingSystems.ToArray())),
                ["category_items"] = JsonValue.String(windowActive && window != null && window.CategoryCombo != null ? JoinObjects(window.CategoryCombo.Items) : string.Empty),
                ["current_page"] = JsonValue.Integer(windowActive && window != null ? window.CurrentPage : 0),
                ["design_teams"] = JsonValue.String(windowActive && window != null ? JoinSorted(window.DesignTeams) : string.Empty),
                ["development_teams"] = JsonValue.String(windowActive && window != null ? JoinSorted(window.DevelopmentTeams) : string.Empty),
                ["page_title"] = JsonValue.String(windowActive && window != null && window.PageTitle != null ? window.PageTitle.text ?? string.Empty : string.Empty),
                ["price"] = JsonValue.Number(windowActive && window != null ? window.Price : 0f),
                ["price_focused"] = JsonValue.Boolean(windowActive && window != null && window.PriceText != null && window.PriceText.isFocused),
                ["price_text"] = JsonValue.String(windowActive && window != null && window.PriceText != null ? window.PriceText.text ?? string.Empty : string.Empty),
                ["product_name"] = JsonValue.String(windowActive && window != null && window.ProductName != null ? window.ProductName.text ?? string.Empty : string.Empty),
                ["product_name_focused"] = JsonValue.Boolean(windowActive && window != null && window.ProductName != null && window.ProductName.isFocused),
                ["scene"] = JsonValue.String(scene),
                ["selected_category"] = JsonValue.String(windowActive && window != null && window.CategoryCombo != null ? window.CategoryCombo.SelectedItemString ?? string.Empty : string.Empty),
                ["selected_features"] = JsonValue.String(string.Join("|", selectedFeatures.ToArray())),
                ["selected_operating_systems"] = JsonValue.String(string.Join("|", selectedOperatingSystems.ToArray())),
                ["selected_type"] = JsonValue.String(windowActive && window != null && window.SelectedType != null ? window.SelectedType.Name : string.Empty),
                ["team_issue"] = JsonValue.String(windowActive && window != null && window.TeamIssueText != null ? window.TeamIssueText.text ?? string.Empty : string.Empty),
                ["team_picker_selected"] = JsonValue.String(teamSelectActive && teamSelect != null ? SelectedTeamToggles(teamSelect) : string.Empty),
                ["type_items"] = JsonValue.String(windowActive && window != null && window.TypeCombo != null ? JoinObjects(window.TypeCombo.Items) : string.Empty),
            }));
            if (!windowActive)
            {
                var buttons = Resources.FindObjectsOfTypeAll<Button>();
                foreach (var button in buttons)
                {
                    if (!Active(button) || button.gameObject.name != "DesignDocumentButton") continue;
                    var callbacks = ButtonCallbacks(button);
                    if (callbacks.IndexOf("HUD.DevelopButton", StringComparison.Ordinal) < 0) continue;
                    AddTarget(entities, "open_product_design", "button", button);
                }
            }
            if (windowActive && window != null)
            {
                var selectedOperatingSystemIds = new HashSet<uint>();
                foreach (var product in window.GetOSs())
                    if (product != null) selectedOperatingSystemIds.Add(product.ID);
                AddTarget(entities, "product_name_input", "input", window.ProductName);
                AddTarget(entities, "product_price_input", "input", window.PriceText);
                AddTarget(entities, "product_type_combo", "combobox", window.TypeCombo);
                AddTarget(entities, "product_category_combo", "combobox", window.CategoryCombo);
                AddTarget(entities, "product_os_list", "list", window.OSList);
                if (window.FeatureCards != null)
                    foreach (var card in window.FeatureCards)
                    {
                        if (card == null || card.Feature == null) continue;
                        AddTarget(entities, "product_feature_" + card.Feature.Name,
                            "feature_toggle", card.MainToggle, card.Feature.GetLocalizedName());
                        entities.Add(Entity("product_feature_selection", card.Feature.Name,
                            new Dictionary<string, JsonValue>
                            {
                                ["localized_name"] = SafeString(card.Feature.GetLocalizedName()),
                                ["selected"] = JsonValue.Boolean(card.MainToggle != null && card.MainToggle.isOn),
                                ["specialization"] = SafeString(card.Feature.Spec),
                            }));
                    }
                AddButtonTargets(entities, observedPaths, "product", window.Window.gameObject);
                AddOperatingSystemRows(entities, window);
                if (window.OSList != null && window.OSList.ActualItems != null)
                    foreach (var item in window.OSList.ActualItems)
                    {
                        var product = item as SoftwareProduct;
                        if (product == null) continue;
                        entities.Add(Entity("operating_system_option",
                            product.ID.ToString(CultureInfo.InvariantCulture),
                            new Dictionary<string, JsonValue>
                            {
                                ["name"] = SafeString(product.Name),
                                ["release_date"] = SafeString(product.Release.ToString()),
                                ["selected"] = JsonValue.Boolean(
                                    selectedOperatingSystemIds.Contains(product.ID)),
                                ["userbase"] = JsonValue.Integer(product.Userbase),
                            }));
                    }
            }
            if (teamSelectActive && teamSelect != null)
            {
                if (teamSelect.ContentPanel != null)
                    foreach (var toggle in teamSelect.ContentPanel.GetComponentsInChildren<TeamToggle>(false))
                        if (Active(toggle) && toggle.MainToggle != null && !string.IsNullOrWhiteSpace(toggle.Team))
                            AddTarget(entities, "product_team_" + toggle.Team, "team_toggle", toggle.MainToggle, toggle.Team);
                AddButtonTargets(entities, observedPaths, "product-team", teamSelect.Window.gameObject);
            }
            var comboPanel = ComboboxPanel.Instance;
            if (comboPanel != null && comboPanel.gameObject.activeInHierarchy)
                AddButtonTargets(entities, observedPaths, "product-combo", comboPanel.gameObject);
            entities.Sort(EntityCompare);
            return Surface("product_ui", CoverageStatus.ObservedComplete,
                new[] { "available_operating_systems", "callbacks", "category_items", "current_page", "design_teams", "development_teams", "height_ratio", "interactable", "kind", "label", "localized_name", "name", "object_name", "page_title", "path", "price", "price_focused", "price_text", "product_name", "product_name_focused", "release_date", "scene", "selected", "selected_category", "selected_features", "selected_operating_systems", "selected_type", "specialization", "team_issue", "team_picker_selected", "type_items", "userbase", "width_ratio", "x_ratio", "y_ratio" },
                "read-only current design-window configuration and normalized visible Unity UI geometry; no design, callback, or product mutation method is invoked",
                entities.ToArray());
        }

        private static string ProductIdentity(SoftwareProduct product)
        {
            return product.ID.ToString(CultureInfo.InvariantCulture) + ":" + (product.Name ?? string.Empty);
        }

        private static void AddOperatingSystemRows(
            List<ObservedEntityState> entities, DesignDocumentWindow window)
        {
            if (window.OSList == null || window.OSList.ActualItems == null) return;
            var rows = window.OSList.GetComponentsInChildren<GUIListItem>(false);
            Array.Sort(rows, (left, right) => left.Idx.CompareTo(right.Idx));
            var seen = new HashSet<int>();
            foreach (var row in rows)
            {
                if (!Active(row) || row.Idx < 0 || row.Idx >= window.OSList.ActualItems.Count ||
                    !seen.Add(row.Idx)) continue;
                var product = window.OSList.ActualItems[row.Idx] as SoftwareProduct;
                if (product == null) continue;
                AddTarget(entities, "product_os_" + product.ID.ToString(CultureInfo.InvariantCulture),
                    "list_row", row, product.Name ?? string.Empty);
            }
        }

        private static JsonValue SafeString(string? value)
        {
            return JsonValue.String(value ?? string.Empty);
        }

        private static ObservationSurfaceState ContractUiSurface()
        {
            var hud = HUD.Instance;
            var window = SingleActive<ContractWindow>();
            var teamSelect = hud != null ? hud.TeamSelectWindow : null;
            var teamSelectActive = window != null && teamSelect != null && Active(teamSelect.Window);
            var startReview = hud != null ? hud.startReviewWindow : null;
            var reviewSetupActive = startReview != null && Active(startReview.Window);
            var reviewResult = hud != null ? hud.reviewWindow : null;
            var reviewResultActive = reviewResult != null && Active(reviewResult.Window);
            var entities = new List<ObservedEntityState>();
            var observedPaths = new HashSet<string>(StringComparer.Ordinal);
            var scene = reviewResultActive ? "contract_review_result"
                : reviewSetupActive ? "contract_review_setup"
                : teamSelectActive && window != null ? "contract_team_selection"
                : window != null ? "contract_browser" : "gameplay";
            entities.Add(Entity("contract_ui_state", "current", new Dictionary<string, JsonValue>
            {
                ["available_tab"] = JsonValue.Boolean(window != null && window.AvailableToggle != null && window.AvailableToggle.isOn),
                ["design_teams"] = JsonValue.String(window == null ? string.Empty : JoinSorted(window.DesignTeams)),
                ["development_teams"] = JsonValue.String(window == null ? string.Empty : JoinSorted(window.DevTeams)),
                ["feature_text"] = JsonValue.String(window != null && window.FeatureList != null ? window.FeatureList.text ?? string.Empty : string.Empty),
                ["lead_designer"] = JsonValue.String(window != null && window.LeadLabel != null ? window.LeadLabel.text ?? string.Empty : string.Empty),
                ["requirements_text"] = JsonValue.String(window != null && window.RequirementsList != null ? window.RequirementsList.text ?? string.Empty : string.Empty),
                ["review_client"] = JsonValue.Boolean(reviewSetupActive && startReview != null && startReview.ClientToggle != null && startReview.ClientToggle.isOn),
                ["review_cost_text"] = JsonValue.String(reviewSetupActive && startReview != null && startReview.MoneyLabel != null ? startReview.MoneyLabel.text ?? string.Empty : string.Empty),
                ["review_internal"] = JsonValue.Boolean(reviewSetupActive && startReview != null && startReview.OutsourceToggle != null && !startReview.OutsourceToggle.isOn),
                ["review_outsource"] = JsonValue.Boolean(reviewSetupActive && startReview != null && startReview.OutsourceToggle != null && startReview.OutsourceToggle.isOn),
                ["review_slider_max"] = JsonValue.Number(reviewSetupActive && startReview != null && startReview.MainSlider != null ? startReview.MainSlider.maxValue : 0f),
                ["review_slider_min"] = JsonValue.Number(reviewSetupActive && startReview != null && startReview.MainSlider != null ? startReview.MainSlider.minValue : 0f),
                ["review_slider_value"] = JsonValue.Number(reviewSetupActive && startReview != null && startReview.MainSlider != null ? startReview.MainSlider.value : 0f),
                ["scene"] = JsonValue.String(scene),
                ["selected_available_indices"] = JsonValue.String(window == null ? string.Empty : SelectedIndices(window.Contracts)),
                ["selected_result_indices"] = JsonValue.String(window == null ? string.Empty : SelectedIndices(window.ContractResults)),
                ["team_picker_selected"] = JsonValue.String(teamSelectActive && teamSelect != null ? SelectedTeamToggles(teamSelect) : string.Empty),
            }));
            if (hud != null && hud.BottomContractButton != null)
            {
                var button = hud.BottomContractButton.GetComponentInChildren<Button>(true);
                AddTarget(entities, "open_contracts", "button", button, "Contracts");
            }
            if (window != null)
            {
                AddContractRows(entities, window.Contracts, "contract_row");
                AddContractRows(entities, window.ContractResults, "contract_result_row");
                AddButtonTargets(entities, observedPaths, "contract", window.gameObject);
            }
            if (teamSelectActive && teamSelect != null)
            {
                if (teamSelect.ContentPanel != null)
                    foreach (var toggle in teamSelect.ContentPanel.GetComponentsInChildren<TeamToggle>(false))
                        if (Active(toggle) && toggle.MainToggle != null && !string.IsNullOrWhiteSpace(toggle.Team))
                            AddTarget(entities, "contract_team_" + toggle.Team, "team_toggle", toggle.MainToggle, toggle.Team);
                AddButtonTargets(entities, observedPaths, "contract-team", teamSelect.Window.gameObject);
            }
            if (reviewSetupActive && startReview != null)
                AddButtonTargets(entities, observedPaths, "contract-review", startReview.Window.gameObject);
            if (reviewResultActive && reviewResult != null)
                AddButtonTargets(entities, observedPaths, "contract-review-result", reviewResult.Window.gameObject);
            if (companyWorkItemsAvailable()) AddWorkItemButtons(entities, observedPaths);
            entities.Sort(EntityCompare);
            return Surface("contract_ui", CoverageStatus.ObservedComplete,
                new[] { "available_tab", "callbacks", "design_teams", "development_teams", "feature_text", "height_ratio", "interactable", "kind", "label", "lead_designer", "object_name", "path", "requirements_text", "review_client", "review_cost_text", "review_internal", "review_outsource", "review_slider_max", "review_slider_min", "review_slider_value", "scene", "selected_available_indices", "selected_result_indices", "team_picker_selected", "width_ratio", "x_ratio", "y_ratio" },
                "read-only contract, team-picker, and work-item UI state with normalized geometry; callbacks are described but never invoked",
                entities.ToArray());
        }

        private static bool companyWorkItemsAvailable()
        {
            return GameSettings.Instance != null && GameSettings.Instance.MyCompany != null;
        }

        private static void AddWorkItemButtons(List<ObservedEntityState> entities, HashSet<string> observedPaths)
        {
            foreach (var item in GameSettings.Instance.MyCompany.WorkItems)
            {
                if (item == null || item.guiItem == null || !Active(item.guiItem)) continue;
                AddButtonTargets(entities, observedPaths,
                    "work-item-" + item.ID.ToString(CultureInfo.InvariantCulture), item.guiItem.gameObject);
            }
        }

        private static void AddContractRows(List<ObservedEntityState> entities, GUIListView list, string prefix)
        {
            if (list == null || list.ActualItems == null) return;
            var rows = list.GetComponentsInChildren<GUIListItem>(false);
            Array.Sort(rows, (left, right) => left.Idx.CompareTo(right.Idx));
            var seen = new HashSet<int>();
            foreach (var row in rows)
            {
                if (!Active(row) || row.Idx < 0 || row.Idx >= list.ActualItems.Count || !seen.Add(row.Idx)) continue;
                var label = list.ActualItems[row.Idx] == null ? string.Empty : list.ActualItems[row.Idx].ToString();
                AddTarget(entities, prefix + "_" + row.Idx.ToString(CultureInfo.InvariantCulture), "list_row", row, label);
            }
        }

        private static string SelectedIndices(GUIListView list)
        {
            if (list == null || list.Selected == null) return string.Empty;
            var values = new List<string>();
            foreach (var index in list.Selected) values.Add(index.ToString(CultureInfo.InvariantCulture));
            values.Sort(StringComparer.Ordinal);
            return string.Join(",", values.ToArray());
        }

        private static string JoinSorted(IEnumerable<string> values)
        {
            var result = new List<string>();
            foreach (var value in values) result.Add(value);
            result.Sort(StringComparer.Ordinal);
            return string.Join("|", result.ToArray());
        }

        private static string SelectedTeamToggles(TeamSelectWindow window)
        {
            var selected = new List<string>();
            if (window.ContentPanel != null)
                foreach (var toggle in window.ContentPanel.GetComponentsInChildren<TeamToggle>(false))
                    if (Active(toggle) && toggle.MainToggle != null && toggle.MainToggle.isOn &&
                        !string.IsNullOrWhiteSpace(toggle.Team)) selected.Add(toggle.Team);
            selected.Sort(StringComparer.Ordinal);
            return string.Join("|", selected.ToArray());
        }

        private static string ContractIdentity(ContractWork work)
        {
            return (work.GetIdentifyingName() ?? work.GetName() ?? "contract").Trim();
        }

        private static ObservationSurfaceState OfficeSurface(GameSettings settings)
        {
            var entities = new List<ObservedEntityState>();
            foreach (var room in settings.sRoomManager.Rooms)
            {
                if (room == null || room.Outside || !room.PlayerOwned) continue;
                var roomId = room.GetRoomNetworkID().ToString(CultureInfo.InvariantCulture);
                var teams = new List<string>();
                foreach (var team in room.Teams) teams.Add(team.Name);
                teams.Sort(StringComparer.Ordinal);
                var assignable = 0;
                var available = 0;
                var valid = 0;
                var furniture = room.GetFurnitures();
                foreach (var item in furniture)
                {
                    if (item == null) continue;
                    var missingRequiredChair = item.NeedsChair && HUD.Instance != null &&
                        HUD.Instance.NoChairPC.Contains(item);
                    // CanAssign also applies to personal facilities such as toilets.  A
                    // usable employee workstation in the supported build is the narrower
                    // public-API conjunction: assignable furniture which requires a chair.
                    var workstation = item.CanAssign && item.NeedsChair;
                    if (workstation)
                    {
                        assignable++;
                        if (item.IsValid && !item.IsBlocked && !missingRequiredChair)
                        {
                            valid++;
                            if (item.OwnedBy == null) available++;
                        }
                    }
                    var owner = item.OwnedBy;
                    var ownerEmployee = owner != null ? owner.employee : null;
                    var snappedTo = item.SnappedTo;
                    var snappedParent = snappedTo != null ? snappedTo.Parent : null;
                    var linkedSnapTargets = new List<string>();
                    if (snappedTo != null && snappedTo.Links != null)
                        foreach (var link in snappedTo.Links)
                            if (link != null && link.Parent != null)
                                linkedSnapTargets.Add(SnapPointTargetIdentity(link));
                    linkedSnapTargets.Sort(StringComparer.Ordinal);
                    var computerChair = item.ComputerChair;
                    float itemXRatio;
                    float itemYRatio;
                    var itemVisible = TryScreenRatios(item.transform.position, out itemXRatio, out itemYRatio);
                    entities.Add(Entity("office_equipment",
                        item.GetInstanceID().ToString(CultureInfo.InvariantCulture),
                        new Dictionary<string, JsonValue>
                        {
                            ["assignable"] = JsonValue.Boolean(item.CanAssign),
                            ["actions"] = JsonValue.String(
                                item.actions == null ? string.Empty : string.Join("|", item.actions)),
                            ["blocked"] = JsonValue.Boolean(item.IsBlocked),
                            ["category"] = JsonValue.String(
                                item.Category == null ? string.Empty : string.Join("|", item.Category)),
                            ["comfort"] = JsonValue.Number(item.Comfort),
                            ["computer_power"] = JsonValue.Number(item.ComputerPower),
                            ["current_wattage"] = JsonValue.Number(item.CurrentWattage),
                            ["environment"] = JsonValue.Number(item.Environment),
                            ["function_category"] = JsonValue.String(item.FunctionCategory ?? string.Empty),
                            ["name"] = JsonValue.String(item.GetDefaultName()),
                            ["needs_chair"] = JsonValue.Boolean(item.NeedsChair),
                            ["missing_required_chair"] = JsonValue.Boolean(missingRequiredChair),
                            ["one_time_cost"] = JsonValue.Number(item.GetCost()),
                            ["owner_employee_id"] = JsonValue.String(ownerEmployee == null
                                ? string.Empty
                                : ownerEmployee.NetworkID.ToString(CultureInfo.InvariantCulture)),
                            ["owner_employee_name"] = JsonValue.String(ownerEmployee == null
                                ? string.Empty
                                : ownerEmployee.FullName),
                            ["prefab_name"] = JsonValue.String(
                                (item.gameObject.name ?? string.Empty).Replace("(Clone)", string.Empty).Trim()),
                            ["rotation_y"] = JsonValue.Number(item.transform.rotation.eulerAngles.y),
                            ["room_id"] = JsonValue.String(roomId),
                            ["computer_chair_equipment_id"] = JsonValue.String(computerChair == null
                                ? string.Empty
                                : computerChair.GetInstanceID().ToString(CultureInfo.InvariantCulture)),
                            ["snapped"] = JsonValue.Boolean(snappedTo != null),
                            ["snapped_to_parent_equipment_id"] = JsonValue.String(snappedParent == null
                                ? string.Empty
                                : snappedParent.GetInstanceID().ToString(CultureInfo.InvariantCulture)),
                            ["snapped_to_point_id"] = JsonValue.String(snappedTo == null
                                ? string.Empty
                                : snappedTo.Id.ToString(CultureInfo.InvariantCulture)),
                            ["snapped_to_point_name"] = JsonValue.String(
                                snappedTo == null ? string.Empty : snappedTo.Name ?? string.Empty),
                            ["snapped_to_linked_target_ids"] = JsonValue.String(
                                string.Join("|", linkedSnapTargets.ToArray())),
                            ["screen_visible"] = JsonValue.Boolean(itemVisible),
                            ["screen_x_ratio"] = JsonValue.Number(itemXRatio),
                            ["screen_y_ratio"] = JsonValue.Number(itemYRatio),
                            ["valid"] = JsonValue.Boolean(item.IsValid),
                            ["type"] = JsonValue.String(item.Type ?? string.Empty),
                            ["world_x"] = JsonValue.Number(item.transform.position.x),
                            ["world_y"] = JsonValue.Number(item.transform.position.y),
                            ["world_z"] = JsonValue.Number(item.transform.position.z),
                        }));
                    if (item.SnapPoints != null)
                        foreach (var point in item.SnapPoints)
                        {
                            if (point == null) continue;
                            var pointLinks = new List<string>();
                            if (point.Links != null)
                                foreach (var link in point.Links)
                                    if (link != null && link.Parent != null)
                                        pointLinks.Add(SnapPointTargetIdentity(link));
                            pointLinks.Sort(StringComparer.Ordinal);
                            var pointPosition = point.GetRealPos();
                            var usedBy = point.MainUsedBy;
                            entities.Add(Entity("office_snap_point", SnapPointIdentity(point),
                                new Dictionary<string, JsonValue>
                                {
                                    ["has_main"] = JsonValue.Boolean(point.HasMain),
                                    ["is_valid"] = JsonValue.Boolean(point.IsValid),
                                    ["linked_target_ids"] = JsonValue.String(
                                        string.Join("|", pointLinks.ToArray())),
                                    ["name"] = JsonValue.String(point.Name ?? string.Empty),
                                    ["parent_equipment_id"] = JsonValue.String(
                                        item.GetInstanceID().ToString(CultureInfo.InvariantCulture)),
                                    ["point_id"] = JsonValue.String(
                                        point.Id.ToString(CultureInfo.InvariantCulture)),
                                    ["rotation_y"] = JsonValue.Number(
                                        point.transform.rotation.eulerAngles.y),
                                    ["room_id"] = JsonValue.String(roomId),
                                    ["target_id"] = JsonValue.String(SnapPointTargetIdentity(point)),
                                    ["use_for_orientation"] = JsonValue.Boolean(point.UseForOrientation),
                                    ["used_by_equipment_id"] = JsonValue.String(usedBy == null
                                        ? string.Empty
                                        : usedBy.GetInstanceID().ToString(CultureInfo.InvariantCulture)),
                                    ["used_by_type"] = JsonValue.String(
                                        usedBy == null ? string.Empty : usedBy.Type ?? string.Empty),
                                    ["world_x"] = JsonValue.Number(pointPosition.x),
                                    ["world_y"] = JsonValue.Number(pointPosition.y),
                                    ["world_z"] = JsonValue.Number(pointPosition.z),
                                }));
                        }
                }
                float roomXRatio;
                float roomYRatio;
                var roomVisible = TryScreenRatios(
                    new Vector3(room.Center.x, room.Floor * 2f, room.Center.y),
                    out roomXRatio,
                    out roomYRatio);
                entities.Add(Entity("office_room", roomId, new Dictionary<string, JsonValue>
                {
                    ["acoustics"] = JsonValue.Number(room.Acoustics),
                    ["area"] = JsonValue.Number(room.Area),
                    ["assignable_workstations"] = JsonValue.Integer(assignable),
                    ["assigned_teams"] = JsonValue.String(string.Join("|", teams.ToArray())),
                    ["available_workstations"] = JsonValue.Integer(available),
                    ["environment"] = JsonValue.Number(room.FurnEnvironment),
                    ["floor"] = JsonValue.Integer(room.Floor),
                    ["is_lit"] = JsonValue.Boolean(room.IsLit()),
                    ["major_problem"] = JsonValue.Boolean(room.MajorProblem),
                    ["occupant_count"] = JsonValue.Integer(room.Occupants.Count),
                    ["problem_count"] = JsonValue.Integer(room.Problems.Count),
                    ["screen_visible"] = JsonValue.Boolean(roomVisible),
                    ["screen_x_ratio"] = JsonValue.Number(roomXRatio),
                    ["screen_y_ratio"] = JsonValue.Number(roomYRatio),
                    ["temperature"] = JsonValue.Number(room.Temperature),
                    ["total_furniture"] = JsonValue.Integer(furniture.Count),
                    ["valid_workstations"] = JsonValue.Integer(valid),
                    ["world_x"] = JsonValue.Number(room.Center.x),
                    ["world_y"] = JsonValue.Number(room.Floor * 2f),
                    ["world_z"] = JsonValue.Number(room.Center.y),
                }));
            }
            entities.Sort(EntityCompare);
            return Surface("offices", CoverageStatus.ObservedComplete,
                new[] {
                    "acoustics", "area", "assignable", "assignable_workstations", "assigned_teams",
                    "actions", "available_workstations", "blocked", "category", "comfort",
                    "computer_chair_equipment_id", "computer_power", "current_wattage", "environment",
                    "floor", "function_category", "has_main", "is_lit", "is_valid", "linked_target_ids",
                    "major_problem", "missing_required_chair", "name", "needs_chair", "occupant_count", "one_time_cost",
                    "owner_employee_id", "owner_employee_name", "parent_equipment_id", "point_id", "prefab_name",
                    "problem_count", "rotation_y", "room_id", "snapped", "snapped_to_linked_target_ids",
                    "snapped_to_parent_equipment_id", "snapped_to_point_id", "snapped_to_point_name", "target_id", "temperature", "type",
                    "screen_visible", "screen_x_ratio", "screen_y_ratio", "total_furniture", "valid",
                    "valid_workstations", "use_for_orientation", "used_by_equipment_id", "used_by_type",
                    "world_x", "world_y", "world_z"
                },
                "all player-owned indoor rooms, furniture, snap relationships, and missing-chair state from public Room, Furniture, SnapPoint, and HUD APIs; only valid unblocked assignable furniture with an observed required chair is treated as workstation capacity",
                entities.ToArray());
        }

        private static ObservationSurfaceState InfrastructureSurface(GameSettings settings)
        {
            var entities = new List<ObservedEntityState>();
            foreach (var group in settings.GetAllServerGroups(false, true))
            {
                if (group == null) continue;
                entities.Add(Entity("server_group", group.Name, new Dictionary<string, JsonValue>
                {
                    ["available"] = JsonValue.Number(group.Available),
                    ["broken"] = JsonValue.Boolean(group.Broken),
                    ["display_name"] = JsonValue.String(group.GetDisplayName()),
                    ["is_cloud"] = JsonValue.Boolean(group.IsCloud),
                    ["item_count"] = JsonValue.Integer(group.Items.Count),
                    ["name"] = JsonValue.String(group.Name),
                    ["recurring_cost"] = JsonValue.Number(group.GetCost()),
                    ["server_count"] = JsonValue.Integer(group.Servers.Count),
                    ["total_power"] = JsonValue.Number(group.PowerSum),
                }));
            }
            entities.Sort(EntityCompare);
            return Surface("infrastructure", CoverageStatus.ObservedComplete,
                new[] { "available", "broken", "display_name", "is_cloud", "item_count", "name", "recurring_cost", "server_count", "total_power" },
                "all current server groups from GameSettings.GetAllServerGroups; no universal team source-control prerequisite is inferred",
                entities.ToArray());
        }

        private static ObservationSurfaceState BuildCatalogSurface()
        {
            var hud = HUD.Instance;
            if (hud == null || hud.AllFurniture == null || hud.SearchPanel == null)
                return ObservationSurfaceState.Unavailable("build_catalog",
                    "the initialized HUD furniture catalog is unavailable");
            var entities = new List<ObservedEntityState>();
            var identities = new Dictionary<string, int>(StringComparer.Ordinal);
            foreach (var item in hud.AllFurniture)
            {
                if (item == null || !item.Queryable()) continue;
                var localized = Localization.GetFurniture(
                    item.GetLocalizationName(), item.GetDefaultName(), item.ButtonDescription);
                var displayName = localized.Length > 0 && !string.IsNullOrWhiteSpace(localized[0])
                    ? localized[0]
                    : item.GetDefaultName();
                GlobalSearchPanel.SearchItem? searchItem;
                var searchable = hud.SearchPanel.TryGetSearchItem(item, out searchItem);
                var baseIdentity = item.gameObject.name ?? displayName;
                int ordinal;
                identities.TryGetValue(baseIdentity, out ordinal);
                identities[baseIdentity] = ordinal + 1;
                var identity = baseIdentity + ":" + ordinal.ToString(CultureInfo.InvariantCulture);
                var snapPoints = new List<string>();
                if (item.SnapPoints != null)
                {
                    foreach (var point in item.SnapPoints)
                        if (point != null && !string.IsNullOrWhiteSpace(point.Name))
                            snapPoints.Add(point.Name);
                }
                snapPoints.Sort(StringComparer.Ordinal);
                entities.Add(Entity("furniture_catalog_item", identity,
                    new Dictionary<string, JsonValue>
                    {
                        ["auto_place_groups"] = JsonValue.String(
                            item.AutoPlaceGroup == null ? string.Empty : string.Join("|", item.AutoPlaceGroup)),
                        ["can_assign"] = JsonValue.Boolean(item.CanAssign),
                        ["can_not_snap"] = JsonValue.Boolean(item.CanNotSnap),
                        ["can_rotate"] = JsonValue.Boolean(item.CanRotate),
                        ["categories"] = JsonValue.String(
                            item.Category == null ? string.Empty : string.Join("|", item.Category)),
                        ["computer_power"] = JsonValue.Number(item.ComputerPower),
                        ["construction"] = JsonValue.Boolean(item.IsConstructionFurniture()),
                        ["display_name"] = JsonValue.String(displayName),
                        ["function_category"] = JsonValue.String(item.FunctionCategory ?? string.Empty),
                        ["in_rent_mode"] = JsonValue.Boolean(item.InRentMode),
                        ["inventory_count"] = JsonValue.Integer(
                            GameSettings.GetInventoryCount(item.gameObject.name ?? string.Empty)),
                        ["is_snapping"] = JsonValue.Boolean(item.IsSnapping),
                        ["needs_chair"] = JsonValue.Boolean(item.NeedsChair),
                        ["one_time_cost"] = JsonValue.Number(item.GetCost()),
                        ["prefab_name"] = JsonValue.String(item.gameObject.name ?? string.Empty),
                        ["search_enabled"] = JsonValue.Boolean(searchable && searchItem != null && searchItem.Enabled),
                        ["search_title"] = JsonValue.String(searchable && searchItem != null
                            ? searchItem.Title ?? displayName
                            : displayName),
                        ["searchable"] = JsonValue.Boolean(searchable),
                        ["snap_points"] = JsonValue.String(string.Join("|", snapPoints.ToArray())),
                        ["snaps_to"] = JsonValue.String(
                            item.SnapsTo == null ? string.Empty : string.Join("|", item.SnapsTo)),
                        ["type"] = JsonValue.String(item.Type ?? string.Empty),
                        ["valid_indoors"] = JsonValue.Boolean(item.ValidIndoors),
                        ["valid_outdoors"] = JsonValue.Boolean(item.ValidOutdoors),
                        ["wattage"] = JsonValue.Number(item.Wattage),
                    }));
            }
            entities.Sort(EntityCompare);
            return Surface("build_catalog", CoverageStatus.ObservedComplete,
                new[] {
                    "auto_place_groups", "can_assign", "can_not_snap", "can_rotate", "categories",
                    "computer_power", "construction", "display_name", "function_category",
                    "in_rent_mode", "inventory_count", "is_snapping", "needs_chair", "one_time_cost", "prefab_name",
                    "search_enabled", "search_title", "searchable", "snap_points", "snaps_to", "type",
                    "valid_indoors", "valid_outdoors", "wattage"
                },
                "all queryable furniture from HUD.AllFurniture with exact localized search titles and current public-API prices; no build callback is invoked",
                entities.ToArray());
        }

        private static ObservationSurfaceState BuildUiSurface(GameSettings settings)
        {
            var entities = new List<ObservedEntityState>();
            var observedPaths = new HashSet<string>(StringComparer.Ordinal);
            var hud = HUD.Instance;
            var search = hud != null ? hud.SearchPanel : null;
            var builder = BuildController.Instance != null
                ? BuildController.Instance.CurrentFurnitureBuilder
                : null;
            var teamSelect = hud != null ? hud.TeamSelectWindow : null;
            var rightClick = SelectorController.Instance != null
                ? SelectorController.Instance.rcPanel
                : null;
            var searchActive = search != null && search.gameObject.activeInHierarchy;
            var teamSelectActive = teamSelect != null && Active(teamSelect.Window);
            var rightClickActive = rightClick != null && rightClick.CenterRing != null &&
                rightClick.CenterRing.gameObject.activeInHierarchy;
            var scene = builder != null ? "furniture_placement"
                : searchActive ? "build_search"
                : teamSelectActive ? "room_team_selection"
                : rightClickActive ? "room_context_menu"
                : hud != null && hud.BuildMode ? "build_mode"
                : "gameplay";
            var builderPrefab = builder != null && builder.FurnPrefab != null
                ? builder.FurnPrefab.GetComponent<Furniture>()
                : null;
            var builderRoom = builder != null ? builder.LastRoom : null;
            var builderXRatio = 0f;
            var builderYRatio = 0f;
            var builderVisible = builder != null &&
                TryScreenRatios(builder.transform.position, out builderXRatio, out builderYRatio);
            var previewValid = builder != null && builderRoom != null &&
                (builder.UsedMaterial == builder.Green || builder.UsedMaterial == builder.GreenInstant);
            var searchResults = new List<string>();
            if (search != null && search.Results != null)
            {
                foreach (var result in search.Results)
                    if (Active(result) && result.Item != null && !string.IsNullOrWhiteSpace(result.Item.Title))
                        searchResults.Add(result.Item.Title);
            }
            var selectedTeams = new List<string>();
            if (teamSelectActive && teamSelect != null && teamSelect.ContentPanel != null)
            {
                foreach (var toggle in teamSelect.ContentPanel.GetComponentsInChildren<TeamToggle>(false))
                    if (Active(toggle) && toggle.MainToggle != null && toggle.MainToggle.isOn &&
                        !string.IsNullOrWhiteSpace(toggle.Team)) selectedTeams.Add(toggle.Team);
            }
            selectedTeams.Sort(StringComparer.Ordinal);
            entities.Add(Entity("build_ui_state", "current", new Dictionary<string, JsonValue>
            {
                ["build_mode"] = JsonValue.Boolean(hud != null && hud.BuildMode),
                ["builder_active"] = JsonValue.Boolean(builder != null),
                ["builder_cost"] = JsonValue.Number(builderPrefab == null ? 0f : builderPrefab.GetCost()),
                ["builder_display_name"] = JsonValue.String(
                    builderPrefab == null ? string.Empty : builderPrefab.GetActualString()),
                ["builder_prefab_name"] = JsonValue.String(
                    builderPrefab == null ? string.Empty : builderPrefab.gameObject.name ?? string.Empty),
                ["builder_room_id"] = JsonValue.String(builderRoom == null
                    ? string.Empty
                    : builderRoom.GetRoomNetworkID().ToString(CultureInfo.InvariantCulture)),
                ["builder_screen_visible"] = JsonValue.Boolean(builderVisible),
                ["builder_screen_x_ratio"] = JsonValue.Number(builderXRatio),
                ["builder_screen_y_ratio"] = JsonValue.Number(builderYRatio),
                ["builder_type"] = JsonValue.String(builderPrefab == null ? string.Empty : builderPrefab.Type),
                ["preview_valid"] = JsonValue.Boolean(previewValid),
                ["right_click_active"] = JsonValue.Boolean(rightClickActive),
                ["room_team_selected"] = JsonValue.String(string.Join("|", selectedTeams.ToArray())),
                ["room_team_pass_through"] = JsonValue.Boolean(
                    teamSelectActive && teamSelect != null && teamSelect.PassThrough != null &&
                    teamSelect.PassThrough.isOn),
                ["scene"] = JsonValue.String(scene),
                ["search_active"] = JsonValue.Boolean(searchActive),
                ["search_focused"] = JsonValue.Boolean(
                    searchActive && search != null && search.SearchField != null && search.SearchField.isFocused),
                ["search_results"] = JsonValue.String(string.Join("|", searchResults.ToArray())),
                ["search_text"] = JsonValue.String(
                    searchActive && search != null && search.SearchField != null
                        ? search.SearchField.text ?? string.Empty
                        : string.Empty),
            }));
            if (searchActive && search != null)
            {
                AddTarget(entities, "build_search_input", "input", search.SearchField);
                if (search.Results != null)
                    for (var index = 0; index < search.Results.Count; index++)
                    {
                        var result = search.Results[index];
                        if (Active(result)) AddTarget(entities,
                            "build_search_result_" + index.ToString(CultureInfo.InvariantCulture),
                            "search_result", result, result.Item != null ? result.Item.Title : string.Empty);
                    }
            }
            if (builder != null && builderVisible)
                AddWorldTarget(entities, "placement_preview", "placement_preview",
                    builderXRatio, builderYRatio, builderRoom == null ? string.Empty :
                    builderRoom.GetRoomNetworkID().ToString(CultureInfo.InvariantCulture));
            if (rightClickActive && rightClick != null && rightClick.Buttons != null)
                foreach (var pair in rightClick.Buttons)
                    if (Active(pair.Key)) AddTarget(entities,
                        "context_" + (pair.Key.gameObject.name ?? string.Empty),
                        "context_action", pair.Key, pair.Key.Description ?? string.Empty);
            if (teamSelectActive && teamSelect != null)
            {
                AddTarget(entities, "room_team_search", "input", teamSelect.SearchBar);
                AddTarget(entities, "room_team_pass_through", "toggle", teamSelect.PassThrough);
                if (teamSelect.ContentPanel != null)
                    foreach (var toggle in teamSelect.ContentPanel.GetComponentsInChildren<TeamToggle>(false))
                        if (Active(toggle) && toggle.MainToggle != null && !string.IsNullOrWhiteSpace(toggle.Team))
                            AddTarget(entities, "room_team_" + toggle.Team, "team_toggle",
                                toggle.MainToggle, toggle.Team);
                AddButtonTargets(entities, observedPaths, "room-team", teamSelect.Window.gameObject);
            }
            AddRoomPlacementCandidates(entities, settings);
            AddPlacedFurnitureTargets(entities, settings);
            entities.Sort(EntityCompare);
            return Surface("build_ui", CoverageStatus.ObservedComplete,
                new[] {
                    "build_mode", "builder_active", "builder_cost", "builder_display_name",
                    "builder_prefab_name", "builder_room_id", "builder_screen_visible",
                    "builder_screen_x_ratio", "builder_screen_y_ratio", "builder_type", "callbacks",
                    "height_ratio", "interactable", "kind", "label", "object_name", "path",
                    "preview_valid", "right_click_active", "room_id", "room_team_pass_through",
                    "room_team_selected", "scene", "search_active", "search_focused", "search_results",
                    "search_text", "width_ratio", "world_x", "world_y", "world_z", "x_ratio", "y_ratio"
                },
                "read-only build/search/preview/context/team-selection state plus normalized visible room points; no callbacks or placement checks are invoked",
                entities.ToArray());
        }

        private static void AddRoomPlacementCandidates(
            List<ObservedEntityState> entities, GameSettings settings)
        {
            foreach (var room in settings.sRoomManager.Rooms)
            {
                if (room == null || room.Outside || !room.PlayerOwned ||
                    room.Floor != settings.ActiveFloor) continue;
                var roomId = room.GetRoomNetworkID().ToString(CultureInfo.InvariantCulture);
                var points = new List<Vector2>();
                // Keep main-thread snapshots bounded even for very large player buildings.
                // A fixed 0.5-unit grid around the public room center is enough to offer
                // multiple empty-room placement previews without scanning every tile.
                for (var xOffset = -8f; xOffset <= 8f; xOffset += 0.5f)
                    for (var yOffset = -8f; yOffset <= 8f; yOffset += 0.5f)
                    {
                        var point = room.Center + new Vector2(xOffset, yOffset);
                        if (!room.RoomBounds.Contains(point)) continue;
                        if (room.IsInside(point, true)) points.Add(point);
                    }
                points.Sort((left, right) =>
                    (left - room.Center).sqrMagnitude.CompareTo((right - room.Center).sqrMagnitude));
                var count = Math.Min(points.Count, 64);
                for (var index = 0; index < count; index++)
                {
                    var point = points[index];
                    float xRatio;
                    float yRatio;
                    if (!TryScreenRatios(new Vector3(point.x, room.Floor * 2f, point.y),
                        out xRatio, out yRatio)) continue;
                    AddWorldTarget(entities,
                        "room_candidate_" + roomId + "_" + index.ToString(CultureInfo.InvariantCulture),
                        "room_candidate", xRatio, yRatio, roomId,
                        point.x, room.Floor * 2f, point.y);
                }
            }
        }

        private static void AddPlacedFurnitureTargets(
            List<ObservedEntityState> entities, GameSettings settings)
        {
            foreach (var room in settings.sRoomManager.Rooms)
            {
                if (room == null || room.Outside || !room.PlayerOwned ||
                    room.Floor != settings.ActiveFloor) continue;
                var roomId = room.GetRoomNetworkID().ToString(CultureInfo.InvariantCulture);
                foreach (var item in room.GetFurnitures())
                {
                    if (item == null) continue;
                    float xRatio;
                    float yRatio;
                    if (!TryScreenRatios(item.transform.position, out xRatio, out yRatio)) continue;
                    AddWorldTarget(entities,
                        "equipment_target_" + item.GetInstanceID().ToString(CultureInfo.InvariantCulture),
                        "equipment", xRatio, yRatio, roomId,
                        item.transform.position.x, item.transform.position.y, item.transform.position.z);
                    if (item.SnapPoints == null) continue;
                    foreach (var point in item.SnapPoints)
                    {
                        if (point == null) continue;
                        var position = point.GetRealPos();
                        float pointXRatio;
                        float pointYRatio;
                        if (!TryScreenRatios(position, out pointXRatio, out pointYRatio)) continue;
                        AddWorldTarget(entities,
                            SnapPointTargetIdentity(point),
                            "equipment_snap_point", pointXRatio, pointYRatio, roomId,
                            position.x, position.y, position.z);
                    }
                }
            }
        }

        private static string SnapPointIdentity(SnapPoint point)
        {
            var parent = point.Parent;
            var parentId = parent == null
                ? "unknown"
                : parent.GetInstanceID().ToString(CultureInfo.InvariantCulture);
            return parentId + ":" + point.Id.ToString(CultureInfo.InvariantCulture);
        }

        private static string SnapPointTargetIdentity(SnapPoint point)
        {
            return "equipment_snap_target_" + SnapPointIdentity(point).Replace(':', '_');
        }

        private static void AddWorldTarget(
            List<ObservedEntityState> entities,
            string identity,
            string kind,
            float xRatio,
            float yRatio,
            string roomId,
            float worldX = 0f,
            float worldY = 0f,
            float worldZ = 0f)
        {
            entities.Add(Entity("world_target", identity, new Dictionary<string, JsonValue>
            {
                ["height_ratio"] = JsonValue.Number(0.012f),
                ["interactable"] = JsonValue.Boolean(true),
                ["kind"] = JsonValue.String(kind),
                ["label"] = JsonValue.String(string.Empty),
                ["room_id"] = JsonValue.String(roomId),
                ["width_ratio"] = JsonValue.Number(0.012f),
                ["world_x"] = JsonValue.Number(worldX),
                ["world_y"] = JsonValue.Number(worldY),
                ["world_z"] = JsonValue.Number(worldZ),
                ["x_ratio"] = JsonValue.Number(xRatio),
                ["y_ratio"] = JsonValue.Number(yRatio),
            }));
        }

        private static bool TryScreenRatios(Vector3 world, out float xRatio, out float yRatio)
        {
            xRatio = 0f;
            yRatio = 0f;
            var camera = CameraScript.Instance != null ? CameraScript.Instance.mainCam : null;
            if (camera == null || Screen.width <= 0 || Screen.height <= 0) return false;
            var screen = camera.WorldToScreenPoint(world);
            if (screen.z <= 0f) return false;
            xRatio = screen.x / Screen.width;
            yRatio = 1f - screen.y / Screen.height;
            return xRatio >= 0f && xRatio <= 1f && yRatio >= 0f && yRatio <= 1f;
        }

        private static ObservationSurfaceState ApplicantSurface()
        {
            var windows = Resources.FindObjectsOfTypeAll<HireWindow>();
            HireWindow? active = null;
            foreach (var window in windows)
            {
                if (window == null || window.gameObject == null || !window.gameObject.activeInHierarchy)
                    continue;
                if (active != null)
                    return FailedSurface("applicants",
                        "multiple active HireWindow instances make applicant identity ambiguous");
                active = window;
            }
            if (active == null)
                return ObservationSurfaceState.Unavailable("applicants",
                    "the visible hiring window is not open");
            if (active.EmployeeList == null || active.EmployeeList.ActualItems == null)
                return FailedSurface("applicants",
                    "the active hiring window has no applicant list");

            var entities = new List<ObservedEntityState>();
            var identities = new HashSet<string>(StringComparer.Ordinal);
            for (var index = 0; index < active.EmployeeList.ActualItems.Count; index++)
            {
                var employee = active.EmployeeList.ActualItems[index] as Employee;
                if (employee == null) continue;
                var identity = employee.NetworkID.ToString(CultureInfo.InvariantCulture);
                if (!identities.Add(identity))
                    return FailedSurface("applicants",
                        "the visible applicant list contains duplicate stable identities");
                var bracket = ApplicantWageBracket(active, employee);
                entities.Add(Entity("applicant", identity, new Dictionary<string, JsonValue>
                {
                    ["available"] = JsonValue.Boolean(employee.MyEmployer == null && !employee.Dismissed),
                    ["display_index"] = JsonValue.Integer(index),
                    ["name"] = JsonValue.String(employee.FullName),
                    ["role"] = JsonValue.String(employee.HiredFor.ToString()),
                    ["salary"] = JsonValue.Number(employee.Salary),
                    ["salary_period"] = JsonValue.String("monthly"),
                    ["selected_team"] = JsonValue.String(active.SelectedTeam ?? string.Empty),
                    ["wage_bracket"] = JsonValue.String(bracket),
                }));
            }
            return Surface("applicants", CoverageStatus.ObservedComplete,
                new[] { "available", "display_index", "name", "role", "salary", "salary_period", "selected_team", "wage_bracket" },
                "complete visible applicant list from the active HireWindow; salary is the game's recurring monthly Employee.Salary value",
                entities.ToArray());
        }

        private static ObservationSurfaceState StaffingUiSurface()
        {
            var teamWindow = SingleActive<TeamWindow>();
            var lookHireWindow = SingleActive<LookHireWindow>();
            var hireWindow = SingleActive<HireWindow>();
            var entities = new List<ObservedEntityState>();
            var observedPaths = new HashSet<string>(StringComparer.Ordinal);
            var scene = "gameplay";
            if (hireWindow != null) scene = "applicant_list";
            else if (lookHireWindow != null) scene = "hiring_setup";
            else if (teamWindow != null && Active(teamWindow.input))
                scene = "create_team_form";
            else if (teamWindow != null) scene = "manage_teams";

            var state = new Dictionary<string, JsonValue>
            {
                ["scene"] = JsonValue.String(scene),
                ["team_name_value"] = JsonValue.String(
                    teamWindow != null && teamWindow.input != null ? teamWindow.input.text : string.Empty),
                ["team_name_focused"] = JsonValue.Boolean(
                    teamWindow != null && teamWindow.input != null && teamWindow.input.isFocused),
                ["selected_team"] = JsonValue.String(
                    hireWindow != null ? hireWindow.SelectedTeam ?? string.Empty : string.Empty),
                ["selected_applicant_indices"] = JsonValue.String(
                    SelectedApplicantIndexes(hireWindow)),
                ["role"] = JsonValue.String(
                    lookHireWindow != null && lookHireWindow.RoleCombo != null
                        ? lookHireWindow.RoleCombo.SelectedItemString ?? string.Empty
                        : lookHireWindow != null && lookHireWindow.LastFilter != null
                        ? lookHireWindow.LastFilter.Role.ToString()
                        : string.Empty),
                ["wage_bracket"] = JsonValue.String(
                    lookHireWindow != null && lookHireWindow.WageBracket != null
                        ? lookHireWindow.WageBracket.SelectedItemString ?? string.Empty
                        : lookHireWindow != null && lookHireWindow.LastFilter != null
                        ? lookHireWindow.LastFilter.Wage.ToString()
                        : string.Empty),
                ["search_cost_text"] = JsonValue.String(
                    lookHireWindow != null && lookHireWindow.CostText != null
                        ? lookHireWindow.CostText.text ?? string.Empty
                        : string.Empty),
                ["pool_text"] = JsonValue.String(
                    lookHireWindow != null && lookHireWindow.PoolText != null
                        ? lookHireWindow.PoolText.text ?? string.Empty
                        : string.Empty),
            };
            entities.Add(Entity("staffing_ui_state", "current", state));

            if (teamWindow != null)
            {
                AddTarget(entities, "team_name_input", "input", teamWindow.input);
                AddButtonTargets(entities, observedPaths, "team", teamWindow.gameObject);
            }
            if (lookHireWindow != null)
            {
                AddTarget(entities, "role_combo", "combobox", lookHireWindow.RoleCombo);
                AddTarget(entities, "wage_combo", "combobox", lookHireWindow.WageBracket);
                AddTarget(
                    entities,
                    "team_compatibility",
                    "button",
                    lookHireWindow.CompatButton != null
                        ? lookHireWindow.CompatButton.GetComponent<RectTransform>()
                        : null);
                AddButtonTargets(entities, observedPaths, "look-hire", lookHireWindow.gameObject);
            }
            if (hireWindow != null)
            {
                AddTarget(entities, "applicant_list", "list", hireWindow.EmployeeList);
                AddApplicantRows(entities, hireWindow);
                AddButtonTargets(entities, observedPaths, "hire", hireWindow.gameObject);
            }
            var comboPanel = ComboboxPanel.Instance;
            if (comboPanel != null && comboPanel.gameObject.activeInHierarchy)
                AddButtonTargets(entities, observedPaths, "combo", comboPanel.gameObject);
            // Keep gameplay toolbar controls semantic and screenshot-bound too.  This avoids
            // guessing a fixed icon coordinate when the HUD layout or aspect ratio changes.
            AddGlobalButtonTargets(entities, observedPaths);

            entities.Sort(EntityCompare);
            return Surface("staffing_ui", CoverageStatus.ObservedComplete,
                new[] {
                    "callbacks", "height_ratio", "interactable", "kind", "label", "object_name", "path",
                    "pool_text", "role", "scene", "search_cost_text", "selected_team",
                    "selected_applicant_indices", "team_name_focused", "team_name_value", "wage_bracket",
                    "width_ratio", "x_ratio", "y_ratio"
                },
                "read-only visible staffing-window state and normalized Unity UI geometry; no callbacks are invoked",
                entities.ToArray());
        }

        private static ObservationSurfaceState OfficeUiSurface()
        {
            var teamWindow = SingleActive<TeamWindow>();
            var employeeWindow = SingleActive<EmployeeWindow>();
            var roleWindow = SingleActive<RoleSelectWindow>();
            var serverWindow = SingleActive<ServerWindow>();
            var entities = new List<ObservedEntityState>();
            var observedPaths = new HashSet<string>(StringComparer.Ordinal);
            var scene = "gameplay";
            if (serverWindow != null) scene = "server_management";
            else if (roleWindow != null) scene = "role_selection";
            else if (employeeWindow != null) scene = "employee_management";
            else if (teamWindow != null) scene = "team_schedules";

            entities.Add(Entity("office_ui_state", "current", new Dictionary<string, JsonValue>
            {
                ["arrival_time"] = JsonValue.String(
                    teamWindow != null && teamWindow.ArrTime != null ? teamWindow.ArrTime.text : string.Empty),
                ["arrival_time_focused"] = JsonValue.Boolean(
                    teamWindow != null && teamWindow.ArrTime != null && teamWindow.ArrTime.isFocused),
                ["departure_time"] = JsonValue.String(
                    teamWindow != null && teamWindow.DepTime != null ? teamWindow.DepTime.text : string.Empty),
                ["departure_time_focused"] = JsonValue.Boolean(
                    teamWindow != null && teamWindow.DepTime != null && teamWindow.DepTime.isFocused),
                ["scene"] = JsonValue.String(scene),
                ["primary_role_states"] = JsonValue.String(RoleStates(roleWindow)),
                ["selected_employees"] = JsonValue.String(SelectedEmployeeIds(employeeWindow)),
                ["selected_teams"] = JsonValue.String(SelectedTeamNames(teamWindow)),
            }));

            if (teamWindow != null)
            {
                AddTarget(entities, "arrival_time_input", "input", teamWindow.ArrTime);
                AddTarget(entities, "departure_time_input", "input", teamWindow.DepTime);
                AddTeamRows(entities, teamWindow);
                AddButtonTargets(entities, observedPaths, "office-team", teamWindow.gameObject);
            }
            if (employeeWindow != null)
            {
                AddEmployeeRows(entities, employeeWindow);
                AddButtonTargets(entities, observedPaths, "office-employee", employeeWindow.gameObject);
            }
            if (roleWindow != null)
            {
                for (var index = 0; index < roleWindow.RoleToggles.Length; index++)
                    AddTarget(entities, "primary_role_" + index.ToString(CultureInfo.InvariantCulture),
                        "role_toggle", roleWindow.RoleToggles[index], RoleName(index));
                for (var index = 0; index < roleWindow.SecondaryRoleToggles.Length; index++)
                    AddTarget(entities, "secondary_role_" + index.ToString(CultureInfo.InvariantCulture),
                        "role_toggle", roleWindow.SecondaryRoleToggles[index], RoleName(index));
                AddTarget(entities, "any_role_toggle", "toggle", roleWindow.AnyRole);
                AddButtonTargets(entities, observedPaths, "office-role", roleWindow.gameObject);
            }
            if (serverWindow != null)
            {
                AddTarget(entities, "server_name_input", "input", serverWindow.InputName);
                AddTarget(entities, "server_list", "list", serverWindow.ServerList);
                AddButtonTargets(entities, observedPaths, "office-server", serverWindow.gameObject);
            }
            if (scene != "gameplay") AddGlobalButtonTargets(entities, observedPaths);

            entities.Sort(EntityCompare);
            return Surface("office_ui", CoverageStatus.ObservedComplete,
                new[] {
                    "arrival_time", "arrival_time_focused", "callbacks", "departure_time", "departure_time_focused", "height_ratio", "interactable", "kind", "label",
                    "object_name", "path", "primary_role_states", "scene", "selected_employees", "selected_teams", "width_ratio",
                    "x_ratio", "y_ratio"
                },
                "read-only schedule, employee-role, and server-management UI state with normalized Unity geometry; no callbacks are invoked",
                entities.ToArray());
        }

        private static ObservationSurfaceState EducationUiSurface()
        {
            var window = SingleActive<EducationWindow>();
            var employeeWindow = SingleActive<EmployeeWindow>();
            var entities = new List<ObservedEntityState>();
            var observedPaths = new HashSet<string>(StringComparer.Ordinal);
            var selectedIds = new List<string>();
            var selectedEmployees = new List<Actor>();
            if (window != null && window.EmployeeList != null &&
                window.EmployeeList.Selected != null && window.EmployeeList.ActualItems != null)
            {
                foreach (var index in window.EmployeeList.Selected)
                {
                    if (index < 0 || index >= window.EmployeeList.ActualItems.Count) continue;
                    var actor = window.EmployeeList.ActualItems[index] as Actor;
                    if (actor == null || actor.employee == null) continue;
                    selectedEmployees.Add(actor);
                    selectedIds.Add(actor.employee.NetworkID.ToString(CultureInfo.InvariantCulture));
                }
            }
            selectedIds.Sort(StringComparer.Ordinal);
            var selectedRole = window == null ? Employee.EmployeeRole.Designer : window.SelectedRole;
            var selectedSpec = window != null && window.SpecCombo != null
                ? window.SpecCombo.SelectedItemString ?? string.Empty
                : string.Empty;
            var selectedCost = 0f;
            if (window != null && selectedEmployees.Count == 1 && !string.IsNullOrWhiteSpace(selectedSpec))
            {
                var actor = selectedEmployees[0];
                var level = actor.employee.GetSpecialization(selectedRole, selectedSpec, actor);
                selectedCost = EducationWindow.GetEducationCost(level);
            }
            entities.Add(Entity("education_ui_state", "current", new Dictionary<string, JsonValue>
            {
                ["duration_months"] = JsonValue.Integer(EducationWindow.EducationMonths),
                ["role_items"] = JsonValue.String(window != null && window.RoleCombo != null ? JoinObjects(window.RoleCombo.Items) : string.Empty),
                ["scene"] = JsonValue.String(window != null ? "education" : employeeWindow != null ? "employee_management" : "gameplay"),
                ["selected_cost"] = JsonValue.Number(selectedCost),
                ["selected_employees"] = JsonValue.String(string.Join("|", selectedIds.ToArray())),
                ["selected_role"] = JsonValue.String(window == null ? string.Empty : selectedRole.ToString()),
                ["selected_specialization"] = JsonValue.String(selectedSpec),
                ["specialization_items"] = JsonValue.String(window != null && window.SpecCombo != null ? JoinObjects(window.SpecCombo.Items) : string.Empty),
                ["start_label"] = JsonValue.String(window != null && window.StartLabel != null ? window.StartLabel.text ?? string.Empty : string.Empty),
            }));
            if (window != null)
            {
                AddTarget(entities, "education_employee_list", "list", window.EmployeeList);
                AddEducationRows(entities, window);
                AddTarget(entities, "education_role_combo", "combobox", window.RoleCombo);
                AddTarget(entities, "education_specialization_combo", "combobox", window.SpecCombo);
                AddButtonTargets(entities, observedPaths, "education", window.gameObject);
                var comboPanel = ComboboxPanel.Instance;
                if (comboPanel != null && comboPanel.gameObject.activeInHierarchy)
                    AddButtonTargets(entities, observedPaths, "education-combo", comboPanel.gameObject);
            }
            if (employeeWindow != null)
            {
                AddEmployeeRows(entities, employeeWindow);
                AddButtonTargets(entities, observedPaths, "education-employee", employeeWindow.gameObject);
            }
            AddGlobalButtonTargets(entities, observedPaths);
            entities.Sort(EntityCompare);
            return Surface("education_ui", CoverageStatus.ObservedComplete,
                new[] { "callbacks", "duration_months", "height_ratio", "interactable", "kind", "label", "object_name", "path", "role_items", "scene", "selected_cost", "selected_employees", "selected_role", "selected_specialization", "specialization_items", "start_label", "width_ratio", "x_ratio", "y_ratio" },
                "read-only education state and normalized visible Unity UI geometry; no education or callback method is invoked",
                entities.ToArray());
        }

        private static string JoinObjects(List<object> values)
        {
            if (values == null) return string.Empty;
            var result = new List<string>();
            foreach (var value in values)
                if (value != null) result.Add(value.ToString());
            return string.Join("|", result.ToArray());
        }

        private static void AddEducationRows(List<ObservedEntityState> entities, EducationWindow window)
        {
            if (window.EmployeeList == null || window.EmployeeList.ActualItems == null) return;
            var rows = window.EmployeeList.GetComponentsInChildren<GUIListItem>(false);
            Array.Sort(rows, (left, right) => left.Idx.CompareTo(right.Idx));
            var seen = new HashSet<int>();
            foreach (var row in rows)
            {
                if (!Active(row) || row.Idx < 0 || row.Idx >= window.EmployeeList.ActualItems.Count ||
                    !seen.Add(row.Idx)) continue;
                var actor = window.EmployeeList.ActualItems[row.Idx] as Actor;
                if (actor == null || actor.employee == null) continue;
                AddTarget(entities,
                    "education_employee_row_" + actor.employee.NetworkID.ToString(CultureInfo.InvariantCulture),
                    "list_row", row, actor.employee.FullName);
            }
        }

        private static string SelectedTeamNames(TeamWindow? window)
        {
            if (window == null || window.TeamList == null || window.TeamList.Selected == null ||
                window.TeamList.ActualItems == null) return string.Empty;
            var names = new List<string>();
            foreach (var index in window.TeamList.Selected)
            {
                if (index < 0 || index >= window.TeamList.ActualItems.Count) continue;
                var team = window.TeamList.ActualItems[index] as Team;
                if (team != null) names.Add(team.Name);
            }
            names.Sort(StringComparer.Ordinal);
            return string.Join("|", names.ToArray());
        }

        private static string RoleStates(RoleSelectWindow? window)
        {
            if (window == null || window.RoleToggles == null) return string.Empty;
            var states = new List<string>();
            for (var index = 0; index < window.RoleToggles.Length; index++)
            {
                var toggle = window.RoleToggles[index];
                states.Add(index.ToString(CultureInfo.InvariantCulture) + ":" +
                    (toggle == null ? "Unavailable" : toggle.CurrentState.ToString()));
            }
            return string.Join("|", states.ToArray());
        }

        private static string SelectedEmployeeIds(EmployeeWindow? window)
        {
            if (window == null || window.EmployeeList == null || window.EmployeeList.Selected == null ||
                window.EmployeeList.ActualItems == null) return string.Empty;
            var identities = new List<string>();
            foreach (var index in window.EmployeeList.Selected)
            {
                if (index < 0 || index >= window.EmployeeList.ActualItems.Count) continue;
                var actor = window.EmployeeList.ActualItems[index] as Actor;
                if (actor != null && actor.employee != null)
                    identities.Add(actor.employee.NetworkID.ToString(CultureInfo.InvariantCulture));
            }
            identities.Sort(StringComparer.Ordinal);
            return string.Join("|", identities.ToArray());
        }

        private static void AddTeamRows(List<ObservedEntityState> entities, TeamWindow window)
        {
            if (window.TeamList == null || window.TeamList.ActualItems == null) return;
            var rows = window.TeamList.GetComponentsInChildren<GUIListItem>(false);
            Array.Sort(rows, (left, right) => left.Idx.CompareTo(right.Idx));
            var seen = new HashSet<int>();
            foreach (var row in rows)
            {
                if (!Active(row) || row.Idx < 0 || row.Idx >= window.TeamList.ActualItems.Count ||
                    !seen.Add(row.Idx)) continue;
                var team = window.TeamList.ActualItems[row.Idx] as Team;
                if (team == null) continue;
                AddTarget(entities, "team_row_" + team.Name, "list_row", row, team.Name);
            }
        }

        private static void AddEmployeeRows(List<ObservedEntityState> entities, EmployeeWindow window)
        {
            if (window.EmployeeList == null || window.EmployeeList.ActualItems == null) return;
            var rows = window.EmployeeList.GetComponentsInChildren<GUIListItem>(false);
            Array.Sort(rows, (left, right) => left.Idx.CompareTo(right.Idx));
            var seen = new HashSet<int>();
            foreach (var row in rows)
            {
                if (!Active(row) || row.Idx < 0 || row.Idx >= window.EmployeeList.ActualItems.Count ||
                    !seen.Add(row.Idx)) continue;
                var actor = window.EmployeeList.ActualItems[row.Idx] as Actor;
                if (actor == null || actor.employee == null) continue;
                AddTarget(entities,
                    "employee_row_" + actor.employee.NetworkID.ToString(CultureInfo.InvariantCulture),
                    "list_row", row, actor.employee.FullName);
            }
        }

        private static string RoleName(int index)
        {
            var names = new[] { "Lead", "Programmer", "Designer", "Artist", "Service" };
            return index >= 0 && index < names.Length ? names[index] : "unknown";
        }

        private static T? SingleActive<T>() where T : Component
        {
            T? active = null;
            foreach (var candidate in Resources.FindObjectsOfTypeAll<T>())
            {
                if (!Active(candidate)) continue;
                if (active != null) return null;
                active = candidate;
            }
            return active;
        }

        private static string SelectedApplicantIndexes(HireWindow? window)
        {
            if (window == null || window.EmployeeList == null || window.EmployeeList.Selected == null)
                return string.Empty;
            var selected = new List<string>();
            foreach (var index in window.EmployeeList.Selected)
                selected.Add(index.ToString(CultureInfo.InvariantCulture));
            selected.Sort(StringComparer.Ordinal);
            return string.Join(",", selected.ToArray());
        }

        private static bool Active(Component? component)
        {
            return component != null && component.gameObject != null &&
                component.gameObject.activeInHierarchy &&
                (!(component is Behaviour behaviour) || behaviour.enabled);
        }

        private static void AddButtonTargets(
            List<ObservedEntityState> entities,
            HashSet<string> observedPaths,
            string prefix,
            GameObject root)
        {
            var buttons = root.GetComponentsInChildren<Button>(false);
            Array.Sort(buttons, (left, right) =>
                string.CompareOrdinal(ComponentPath(left.transform), ComponentPath(right.transform)));
            for (var index = 0; index < buttons.Length; index++)
            {
                var button = buttons[index];
                if (!Active(button)) continue;
                var path = ComponentPath(button.transform);
                if (!observedPaths.Add(path)) continue;
                var text = button.GetComponentInChildren<Text>(false);
                AddTarget(
                    entities,
                    prefix + "-button-" + index.ToString(CultureInfo.InvariantCulture),
                    "button",
                    button,
                    text != null ? text.text ?? string.Empty : string.Empty);
            }
        }

        private static void AddGlobalButtonTargets(
            List<ObservedEntityState> entities,
            HashSet<string> observedPaths)
        {
            var buttons = Resources.FindObjectsOfTypeAll<Button>();
            Array.Sort(buttons, (left, right) =>
                string.CompareOrdinal(ComponentPath(left.transform), ComponentPath(right.transform)));
            for (var index = 0; index < buttons.Length; index++)
            {
                var button = buttons[index];
                if (!Active(button)) continue;
                var path = ComponentPath(button.transform);
                if (!observedPaths.Add(path)) continue;
                var text = button.GetComponentInChildren<Text>(false);
                AddTarget(
                    entities,
                    "global-button-" + index.ToString(CultureInfo.InvariantCulture),
                    "button",
                    button,
                    text != null ? text.text ?? string.Empty : string.Empty);
            }
        }

        private static void AddApplicantRows(
            List<ObservedEntityState> entities, HireWindow window)
        {
            if (window.EmployeeList == null || window.EmployeeList.ActualItems == null) return;
            var rows = window.EmployeeList.GetComponentsInChildren<GUIListItem>(false);
            var seen = new HashSet<int>();
            Array.Sort(rows, (left, right) => left.Idx.CompareTo(right.Idx));
            foreach (var row in rows)
            {
                if (!Active(row) || row.Idx < 0 || row.Idx >= window.EmployeeList.ActualItems.Count ||
                    !seen.Add(row.Idx))
                    continue;
                AddTarget(
                    entities,
                    "applicant_row_" + row.Idx.ToString(CultureInfo.InvariantCulture),
                    "list_row",
                    row);
            }
        }

        private static void AddTarget(
            List<ObservedEntityState> entities,
            string identity,
            string kind,
            Component? component,
            string label = "")
        {
            if (!Active(component)) return;
            var rect = component!.transform as RectTransform;
            if (rect == null) return;
            var canvas = rect.GetComponentInParent<Canvas>();
            var rootCanvas = canvas != null ? canvas.rootCanvas : null;
            var rootRect = rootCanvas != null ? rootCanvas.transform as RectTransform : null;
            if (rootRect == null || rootRect.rect.width <= 0f || rootRect.rect.height <= 0f) return;
            var corners = new Vector3[4];
            rect.GetWorldCorners(corners);
            var first = rootRect.InverseTransformPoint(corners[0]);
            var minimumX = first.x;
            var maximumX = first.x;
            var minimumY = first.y;
            var maximumY = first.y;
            for (var index = 1; index < corners.Length; index++)
            {
                var local = rootRect.InverseTransformPoint(corners[index]);
                minimumX = Math.Min(minimumX, local.x);
                maximumX = Math.Max(maximumX, local.x);
                minimumY = Math.Min(minimumY, local.y);
                maximumY = Math.Max(maximumY, local.y);
            }
            if (maximumX <= minimumX || maximumY <= minimumY) return;
            var rootBounds = rootRect.rect;
            var selectable = component as UnityEngine.UI.Selectable;
            var button = component as Button;
            entities.Add(Entity("ui_target", identity, new Dictionary<string, JsonValue>
            {
                ["callbacks"] = JsonValue.String(ButtonCallbacks(button)),
                ["height_ratio"] = JsonValue.Number((maximumY - minimumY) / rootBounds.height),
                ["interactable"] = JsonValue.Boolean(selectable == null || selectable.interactable),
                ["kind"] = JsonValue.String(kind),
                ["label"] = JsonValue.String(label.Trim()),
                ["object_name"] = JsonValue.String(component.gameObject.name ?? string.Empty),
                ["path"] = JsonValue.String(ComponentPath(component.transform)),
                ["width_ratio"] = JsonValue.Number((maximumX - minimumX) / rootBounds.width),
                ["x_ratio"] = JsonValue.Number(
                    (((minimumX + maximumX) / 2f) - rootBounds.xMin) / rootBounds.width),
                ["y_ratio"] = JsonValue.Number(
                    1f - ((((minimumY + maximumY) / 2f) - rootBounds.yMin) / rootBounds.height)),
            }));
        }

        private static string ButtonCallbacks(Button? button)
        {
            if (button == null || button.onClick == null) return string.Empty;
            var callbacks = new List<string>();
            for (var index = 0; index < button.onClick.GetPersistentEventCount(); index++)
            {
                var target = button.onClick.GetPersistentTarget(index);
                var method = button.onClick.GetPersistentMethodName(index);
                callbacks.Add((target == null ? string.Empty : target.GetType().Name) + "." + method);
            }
            callbacks.Sort(StringComparer.Ordinal);
            return string.Join("|", callbacks.ToArray());
        }

        private static string ComponentPath(Transform transform)
        {
            var parts = new List<string>();
            for (var current = transform; current != null; current = current.parent)
                parts.Add(current.gameObject.name ?? string.Empty);
            parts.Reverse();
            return string.Join("/", parts.ToArray());
        }

        private static string ApplicantWageBracket(HireWindow window, Employee applicant)
        {
            if (window.HirePool == null) return "unknown";
            foreach (var pair in window.HirePool)
            {
                if (pair.Value != null && pair.Value.Contains(applicant))
                    return pair.Key.Value.ToString();
            }
            return "unknown";
        }

        private static ObservationSurfaceState CountSurface(string surface, string entityType, int count, string detail)
        {
            return Surface(surface, CoverageStatus.ObservedPartial, new[] { "count" }, detail,
                Entity(entityType, "collection", new Dictionary<string, JsonValue> { ["count"] = JsonValue.Integer(count) }));
        }

        private static ObservationSurfaceState FailedSurface(string surface, string detail)
        {
            return new ObservationSurfaceState
            {
                Surface = surface,
                Status = CoverageStatus.Failed,
                Detail = detail,
            };
        }

        private static ObservationSurfaceState Surface(string name, CoverageStatus status, string[] fields,
            string detail, params ObservedEntityState[] entities)
        {
            Array.Sort(fields, StringComparer.Ordinal);
            return new ObservationSurfaceState { Surface = name, Status = status, Fields = fields, Detail = detail, Entities = entities };
        }

        private static ObservedEntityState Entity(string type, string id, Dictionary<string, JsonValue> values)
        {
            return new ObservedEntityState { EntityType = type, EntityId = id, Values = values };
        }

        private static int EntityCompare(ObservedEntityState left, ObservedEntityState right)
        {
            var type = string.CompareOrdinal(left.EntityType, right.EntityType);
            return type != 0 ? type : string.CompareOrdinal(left.EntityId, right.EntityId);
        }

        private void AssertMainThread()
        {
            if (Thread.CurrentThread.ManagedThreadId != mainThreadId)
                throw new InvalidOperationException("Software Inc APIs may only be read on the Unity main thread");
        }
    }
}
