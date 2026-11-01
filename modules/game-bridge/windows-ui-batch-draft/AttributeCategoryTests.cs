using FootballAssistant.GameBridge;

// Independent literal Mac topology and synthetic values, not live Windows evidence.
internal static class AttributeCategoryTests
{
    private static void Check(bool condition,string message)
    { if(!condition) throw new Exception("Attribute category fixture: "+message); }
    internal static void Run()
    {
        var at=DateTimeOffset.Parse("2026-01-01T00:00:00Z");
        var context=new SmokeContext(12,"category-fixture",new string('a',64),new string('b',64),"FixtureWindow",34);
        var identity=new WindowsThreadIdentity(0,12,0,34,0,34,false)
        { WindowScanStatus="complete",WindowScanCount=1,WindowCandidates=new[]
            {new WindowsWindowDiagnostic(56,12,34,true,"FixtureWindow",true,0,true,true,10,10,0)} };
        DiscoveryPolicy Policy(string category,string profile) => new(new(context,Guid.NewGuid(),0,
            BatchTreeFixture.CategoryFocus(category),at,at.AddSeconds(120),true,profile));
        DiscoveryResult Capture(DiscoveryPolicy policy,BatchTreeFixture fixture,Func<double>? elapsed=null,
            Func<WindowsThreadIdentity>? fresh=null) => TargetedDiscoveryCollector.Run(policy,
            new(3,policy.Approval.Nonce,policy.ApprovalSha256),()=>new BatchNativeBackend(context.GameHash,fixture.Bind),
            fresh??(()=>identity),()=>at,elapsedForTest:elapsed??(()=>0))!;
        string[] Paths(string category,int first,int count)
        {
            var paths=new List<string>{BatchTreeFixture.CategoryFocus(category)+"/0"};
            for(var row=first;row<first+count;row++)
            {paths.Add(BatchTreeFixture.CategoryLabel(category,row));paths.Add(BatchTreeFixture.CategoryValue(category,row));}
            return paths.ToArray();
        }
        void Clean(BatchTreeFixture fixture,DiscoveryPolicy policy,DiscoveryResult result)
        {
            Check(policy.Terminal && fixture.LiveRoots==0 && fixture.RootCreates==fixture.RootFrees,
                "cleanup and terminal accounting on every path");
            Check(result.NativeOperations==policy.TotalOperations && result.ElapsedMilliseconds==policy.TotalMilliseconds &&
                result.NativeOperations<=2048 && result.Nodes<=96 && result.TotalRoots<=512 && result.PeakRoots<=64 && !result.PageIdentityVerified,
                "unchanged operation/time accounting, node/root caps, unknown identity");
        }
        var expectedProfiles=new List<string>();
        var profiles=0;var totalUnits=0;var totalNodes=0;var totalRoots=0;var totalChecks=0;
        foreach(var category in new[]{"goalkeeper","mental","physical"})
        {
            var labels=BatchTreeFixture.CategoryLabels(category);
            for(var first=0;first<labels.Length;first+=2)
            {
                var count=Math.Min(2,labels.Length-first);var profile=$"{category}_rows{first}_{first+count-1}";
                expectedProfiles.Add(profile);
                Check(AttributeRowSelection.TryGet(profile,out var selection),"exact fixed profile exists");
                var paths=Paths(category,first,count);
                Check(selection.FocusRoot==BatchTreeFixture.CategoryFocus(category) && selection.Category==category &&
                    selection.RowStart==first && selection.RowCount==count && selection.Title==BatchTreeFixture.CategoryTitle(category) &&
                    labels.All(selection.AllowsLabel) && !selection.AllowsLabel("TEST-UNKNOWN") && selection.GetPaths().SequenceEqual(paths),
                    "production selection equals independently expanded literal Mac topology");
                Check(paths.Max(p=>p.Split('/').Length)==(category=="physical"?45:44),"deepest target remains below global48");
                using var fixture=new BatchTreeFixture();fixture.BuildAttributeCategory(category);
                var policy=Policy(category,profile);var checks=0;
                var result=Capture(policy,fixture,fresh:()=>{checks++;return identity;});
                var units=count==1?961:category=="physical"?1323:1305;
                var nodes=count==1?49:category=="physical"?68:67;
                var roots=count==1?153:category=="physical"?212:209;
                Check(result.Status=="raw_diagnostics" && result.Observations.Select(o=>o.Path).SequenceEqual(paths) &&
                    result.NativeOperations==units && result.Nodes==nodes && result.TotalRoots==roots && result.PeakRoots==21 &&
                    checks==units+nodes+3,"exact per-category scoped native costs, no skipped checks");
                Check(fixture.TextReads.SequenceEqual(paths.Select(fixture.NodeAt)) && fixture.PanelOpens==1,
                    "only selected title/label/value getters from one panel");
                var edges=new List<(nint Parent,int Index)>();
                void Visit(string prefix)
                {
                    foreach(var index in paths.Where(p=>prefix.Length==0 || p.StartsWith(prefix+"/",StringComparison.Ordinal))
                        .Select(p=>p[(prefix.Length==0?0:prefix.Length+1)..].Split('/')[0]).Select(int.Parse).Distinct().OrderBy(i=>i))
                    {
                        edges.Add((fixture.NodeAt(prefix),index));
                        var next=prefix.Length==0?index.ToString():prefix+"/"+index;
                        if(!paths.Contains(next)) Visit(next);
                    }
                }
                Visit("");
                Check(fixture.ChildEdges.SequenceEqual(edges) && edges.Count==nodes-1,
                    "exact selected trie; other categories/siblings/rows never obtained");
                var parent=fixture.NodeAt(BatchTreeFixture.CategoryFocus(category)+"/2/0/0/0");
                Check(fixture.ChildEdges.Where(e=>e.Parent==parent).Select(e=>e.Index).SequenceEqual(Enumerable.Range(first,count)),
                    "all available unselected rows including extra last row stay unread");
                Check(GroupedDiscoveryValidation.TryValidate(result,profile,out var observed) && observed.SequenceEqual(labels.Skip(first).Take(count)),
                    "actual observed labels validate, including singleton final goalkeeper row");
                // Whitelist is not an index map: another allowed, nonduplicate label must validate.
                var alternative=labels.First(l=>!observed.Contains(l));
                var changed=result with {Observations=result.Observations.Select((o,i)=>i==1?o with {Text=alternative}:o).ToArray()};
                Check(GroupedDiscoveryValidation.TryValidate(changed,profile,out _),"never infer label from row number");
                foreach(var bad in new[]{"TEST-UNKNOWN", " "+labels[first], labels[first]+"\u200d"})
                    Check(!GroupedDiscoveryValidation.TryValidate(result with {Observations=result.Observations.Select((o,i)=>i==1?o with {Text=bad}:o).ToArray()},profile,out _),
                        "unknown/noncanonical label denied");
                Check(!GroupedDiscoveryValidation.TryValidate(result with {Observations=result.Observations[..^1]},profile,out _),"missing row member denied");
                Clean(fixture,policy,result);
                profiles++;totalUnits+=units;totalNodes+=nodes;totalRoots+=roots;totalChecks+=checks;
            }
        }
        Check(AttributeRowSelection.ManifestProfiles("profile_all_rows").SequenceEqual(expectedProfiles),
            "full manifest preserves exactly the independently enumerated18 fixed selections");
        Check(profiles==18 && totalUnits==23218 && totalNodes==1192 && totalRoots==3718 && totalChecks==24464,
            "whole18-chunk manifest source costs; not one native request or a timing promise");
        foreach(var bad in new[]{"goalkeeper_rows12_13","goalkeeper_rows13_13","mental_rows14_15","physical_rows8_9",
            "mental_rows1_2","physical_rows0_3","mental_rows00_1","unknown_rows0_1"})
            Check(!AttributeRowSelection.TryGet(bad,out _),"no arbitrary range or category selection");
        foreach(var category in new[]{"goalkeeper","mental","physical"})
        foreach(var failure in new[]{"hidden","title","missing","work","hard","cleanup"})
        {
            using var fixture=new BatchTreeFixture();fixture.BuildAttributeCategory(category);
            if(failure=="hidden") fixture.HiddenNodes.Add(fixture.NodeAt(BatchTreeFixture.CategoryValue(category,1)));
            if(failure=="title") fixture.SetNodeText(BatchTreeFixture.CategoryFocus(category)+"/0","TEST-WRONG-CATEGORY");
            if(failure=="missing")
            {var path=BatchTreeFixture.CategoryValue(category,1);fixture.Children[fixture.NodeAt(path[..path.LastIndexOf('/')])].Clear();}
            if(failure=="cleanup") fixture.FailFirstFree=true;
            var profile=category+"_rows0_1";var policy=Policy(category,profile);
            var result=Capture(policy,fixture,elapsed:()=> failure=="work" && fixture.TextReads.Count>0 ?801:
                failure=="hard" && fixture.RootCreates>0 && fixture.LiveRoots==0 ?1001:0);
            if(failure=="title")
                Check(result.Status=="raw_diagnostics" && !GroupedDiscoveryValidation.TryValidate(result,profile,out _),
                    "raw wrong title cannot become semantically publishable category");
            else Check(result.Status=="terminal_failure" && result.Observations.Length==0,"whole group discarded after "+failure);
            Clean(fixture,policy,result);
        }
        Console.WriteLine("Attribute category fixtures:18 fixed chunks,23218 units1192nodes3718roots24464guards; synthetic only, no timing/game claim.");
    }
}
