using FootballAssistant.GameBridge;

// Owned synthetic buffers only. Costs are deterministic source assertions, not live timings.
internal static class GroupedDiscoveryCollectorTests
{
    private static void Check(bool value, string message)
    { if (!value) throw new Exception("Grouped discovery fixture: " + message); }
    internal static void Run()
    {
        var at = DateTimeOffset.Parse("2026-01-01T00:00:00Z");
        var context = new SmokeContext(12, "group-fixture", new string('a',64), new string('b',64), "FixtureWindow", 34);
        var identity = new WindowsThreadIdentity(0,12,0,34,0,34,false)
        { WindowScanStatus="complete", WindowScanCount=1, WindowCandidates=new[]
            { new WindowsWindowDiagnostic(56,12,34,true,"FixtureWindow",true,0,true,true,10,10,0) } };
        DiscoveryPolicy Policy(string profile) => new(new(context, Guid.NewGuid(),0,
            BatchTreeFixture.GoalkeeperCategoryPath,at,at.AddSeconds(120),true,SelectionProfile:profile));
        DiscoveryRequest Request(DiscoveryPolicy policy) => new(3,policy.Approval.Nonce,policy.ApprovalSha256);
        DiscoveryResult Capture(DiscoveryPolicy policy, BatchTreeFixture fixture,
            Func<WindowsThreadIdentity>? fresh=null, Func<double>? elapsed=null) =>
            TargetedDiscoveryCollector.Run(policy,Request(policy),() => new BatchNativeBackend(context.GameHash,fixture.Bind),
                fresh ?? (() => identity),() => at,elapsedForTest:elapsed ?? (() => 0))!;
        string[] Paths(int first) => new[] { BatchTreeFixture.GoalkeeperTitlePath,
            BatchTreeFixture.GroupedLabelPath(first),BatchTreeFixture.GroupedValuePath(first),
            BatchTreeFixture.GroupedLabelPath(first+1),BatchTreeFixture.GroupedValuePath(first+1) };
        void Clean(BatchTreeFixture fixture, DiscoveryPolicy policy, DiscoveryResult result)
        {
            Check(policy.Terminal && policy.Consumed && fixture.LiveRoots==0 && fixture.RootCreates==fixture.RootFrees,
                "all strong roots released exactly once and request terminal");
            Check(result.NativeOperations==policy.TotalOperations && result.ElapsedMilliseconds==policy.TotalMilliseconds &&
                result.NativeOperations<=2048 && result.Nodes<=96 && result.PeakRoots<=64 && result.TotalRoots<=512,
                "unchanged hard budgets and full accounting");
            Check(!result.PageIdentityVerified,"no identity promotion");
        }
        foreach (var first in new[] {0,2})
        {
            var profile=first==0 ? "goalkeeper_rows0_1" : "goalkeeper_rows2_3";
            using var fixture=new BatchTreeFixture(); fixture.BuildGoalkeeperRows(first);
            var policy=Policy(profile); var checks=0;
            var result=Capture(policy,fixture,() => {checks++;return identity;});
            var paths=Paths(first);
            Check(result.Status=="raw_diagnostics" && result.Observations.Select(o=>o.Path).SequenceEqual(paths),
                "exact title and selected pair only, no fallback to other rows");
            Check(result.NativeOperations==1305 && result.Nodes==67 && result.TotalRoots==209 && result.PeakRoots==21 && checks==1375,
                "two-row shared trie exact reserved units/nodes/roots/guards");
            Check(fixture.TextReads.SequenceEqual(paths.Select(fixture.NodeAt)) && fixture.PanelOpens==1,
                "five selected getters from one panel");
            var edges=new List<(nint Parent,int Index)>();
            void Visit(string prefix)
            {
                foreach(var index in paths.Where(p=>prefix.Length==0 || p.StartsWith(prefix+"/",StringComparison.Ordinal))
                    .Select(p=>p[(prefix.Length==0 ? 0 : prefix.Length+1)..].Split('/')[0]).Select(int.Parse).Distinct().OrderBy(i=>i))
                {
                    edges.Add((fixture.NodeAt(prefix),index));
                    var next=prefix.Length==0 ? index.ToString() : prefix+"/"+index;
                    if(!paths.Contains(next)) Visit(next);
                }
            }
            Visit("");
            Check(edges.Count==66 && fixture.ChildEdges.SequenceEqual(edges),"every fetched edge belongs to independently built selected trie");
            var rowParent=fixture.NodeAt(BatchTreeFixture.GoalkeeperCategoryPath+"/2/0/0/0");
            Check(fixture.ChildEdges.Where(e=>e.Parent==rowParent).Select(e=>e.Index).SequenceEqual(new[]{first,first+1}),
                "other available rows never fetched");
            Check(GroupedDiscoveryValidation.TryValidate(result,profile,out var labels) && labels.Length==2 && labels.Distinct().Count()==2,
                "complete same-event category, observed labels and canonical values validate");
            Check(!GroupedDiscoveryValidation.TryValidate(result,first==0 ? "goalkeeper_rows2_3" : "goalkeeper_rows0_1",out _),
                "different profile cannot relabel same observations");
            Clean(fixture,policy,result);
            Check(TargetedDiscoveryCollector.Run(policy,Request(policy),()=>throw new Exception("replay bound exports"),
                ()=>identity,()=>at,elapsedForTest:()=>0) is null,"replay never reaches backend");
            Console.WriteLine($"Grouped {profile}: units=1305 nodes=67 roots=209 peak=21 guards=1375; synthetic zero elapsed only.");

            DiscoveryResult Replace(int index,string text) => result with
            { Observations=result.Observations.Select((o,i)=>i==index ? o with { Text=text } : o).ToArray() };
            Check(GroupedDiscoveryValidation.TryValidate(Replace(1,result.Observations[1].Text.Insert(1,"\u200b")),profile,out _),
                "only observed zero-width space removal accepted");
            foreach(var bad in new[]{"0","21","01","+1","1.0","1-2","１"," 12","12 ","12\u200d","<b>12</b>"})
                Check(!GroupedDiscoveryValidation.TryValidate(Replace(2,bad),profile,out _),"noncanonical value rejected: "+bad);
            Check(!GroupedDiscoveryValidation.TryValidate(Replace(3,result.Observations[1].Text),profile,out _),"duplicate observed labels rejected");
            Check(!GroupedDiscoveryValidation.TryValidate(Replace(0,"精神"),profile,out _),"wrong category rejected");
            Check(!GroupedDiscoveryValidation.TryValidate(Replace(1,"TEST-UNKNOWN"),profile,out _),"unknown label rejected");
            Check(!GroupedDiscoveryValidation.TryValidate(Replace(1," "+result.Observations[1].Text),profile,out _),"label whitespace not normalized");
            Check(!GroupedDiscoveryValidation.TryValidate(result with {Observations=result.Observations[..^1]},profile,out _),"missing member rejects group");
            Check(!GroupedDiscoveryValidation.TryValidate(result with {Observations=result.Observations.Append(result.Observations[0]).ToArray()},profile,out _),"duplicate path rejects group");
        }
        {
            var first=Policy("goalkeeper_rows0_1");
            var replaced=new DiscoveryPolicy(first.Approval with {SelectionProfile="goalkeeper_rows2_3"});
            Check(first.ApprovalSha256!=replaced.ApprovalSha256 && replaced.TryBegin(Request(first),identity,at) is null && !replaced.Consumed,
                "selection profile is immutable grant digest input; request replacement cannot widen scope");
        }
        {
            var original = Policy("goalkeeper_rows0_1");
            var mismatch = new DiscoveryPolicy(original.Approval, requiredWindow: 57);
            Check(mismatch.TryBegin(Request(mismatch), identity, at) is null && mismatch.Consumed && mismatch.Terminal,
                "replacement between outer and child admission rejected before backend binding");
            var matching = new DiscoveryPolicy(original.Approval, requiredWindow: 56);
            Check(matching.TryBegin(Request(matching), identity, at) is not null,
                "same freshly verified HWND satisfies outer equality fence without cached scan");
            matching.Stop();
        }
        foreach(var failure in new[]{"hidden","missing","getter","cleanup","cooperative","hard","final_guard"})
        {
            using var fixture=new BatchTreeFixture();fixture.BuildGoalkeeperRows(0);
            var last=BatchTreeFixture.GroupedValuePath(1);
            if(failure=="hidden") fixture.HiddenNodes.Add(fixture.NodeAt(last));
            if(failure=="missing") fixture.Children[fixture.NodeAt(last[..last.LastIndexOf('/')])].Clear();
            if(failure=="getter") fixture.ThrowingTextNodes.Add(fixture.NodeAt(last));
            if(failure=="cleanup") fixture.FailFirstFree=true;
            var policy=Policy("goalkeeper_rows0_1");
            var result=Capture(policy,fixture,
                ()=>failure=="final_guard" && fixture.RootCreates>0 && fixture.LiveRoots==0 ? identity with {WindowScanStatus="failed"} : identity,
                ()=>failure=="cooperative" && fixture.TextReads.Count>0 ? 801 :
                    failure=="hard" && fixture.RootCreates>0 && fixture.LiveRoots==0 ? 1001 : 0);
            Check(result.Status=="terminal_failure" && result.Observations.Length==0,"whole group discarded after "+failure);
            if(failure is "getter" or "final_guard" or "hard") Check(fixture.TextReads.Count==5,"late failure occurs after earlier provisional targets");
            Clean(fixture,policy,result);
        }
        {
            using var fixture=new BatchTreeFixture();fixture.BuildGoalkeeperRows(0);
            var active=true;
            var original=Policy("goalkeeper_rows0_1");
            var policy=new DiscoveryPolicy(original.Approval,additionalActive:()=>active);
            var result=Capture(policy,fixture,()=> { if(fixture.TextReads.Count>0) active=false; return identity; });
            Check(result.Status=="terminal_failure" && result.Observations.Length==0 && fixture.TextReads.Count==1 && fixture.StringLengthReads==0,
                "outer revocation is checked before the next native text primitive, not another whole target");
            Clean(fixture,policy,result);
            var denied=new DiscoveryPolicy(original.Approval,additionalActive:()=>false);
            Check(denied.TryBegin(Request(denied),identity,at) is null,"outer revoked batch cannot admit a native request");
        }
        {
            using var fixture=new BatchTreeFixture {InheritedContainerMethods=true};fixture.BuildGoalkeeperRows(0);
            var policy=Policy("goalkeeper_rows0_1");var result=Capture(policy,fixture);
            // Three container getters each traverse33->40->41->42->cached27:
            // eight reserved exports instead of one direct lookup, +7*3 units.
            Check(result.Status=="raw_diagnostics" && result.NativeOperations==1326 && fixture.ParentLookups==12 &&
                result.TotalRoots==209 && result.Nodes==67,"real inherited getter export overhead is charged, not hidden or cached across requests");
            Clean(fixture,policy,result);
        }
    }
}
