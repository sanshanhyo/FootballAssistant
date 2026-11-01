using FootballAssistant.GameBridge;

// Exercises actual finite policy + child policy + native adapter, using owned fake
// exports. Does not start the Windows host/timer or prove real latency/page stability.
internal static class FiniteRowsCompositionTests
{
    private static void Check(bool condition,string message)
    { if(!condition) throw new Exception("Finite rows composition: "+message); }
    internal static void Run()
    {
        var epoch=DateTimeOffset.Parse("2026-01-01T00:00:00Z");
        var context=new SmokeContext(12,"composition-fixture",new string('a',64),new string('b',64),"FixtureWindow",34);
        var identity=new WindowsThreadIdentity(0,12,0,34,0,34,false)
        { WindowScanStatus="complete",WindowScanCount=1,WindowCandidates=new[]
            {new WindowsWindowDiagnostic(56,12,34,true,"FixtureWindow",true,0,true,true,10,10,0)} };
        FiniteRowsPolicy NewPolicy() => new(new(context,Guid.NewGuid(),Guid.NewGuid(),Guid.NewGuid(),Guid.NewGuid(),
            epoch,epoch.AddSeconds(120),true,true));
        FiniteRowsRequest Request(FiniteRowsPolicy policy,int index) => new(4,policy.Approval.BatchId,policy.Approval.PageEpoch,
            index,index==0 ? policy.Approval.FirstNonce : policy.Approval.SecondNonce,policy.ApprovalSha256);
        DiscoveryPolicy Child(FiniteRowsPolicy outer,FiniteRowsGrant grant,Func<double> monotonic) =>
            new(new(context,grant.Request.Nonce,0,BatchTreeFixture.GoalkeeperCategoryPath,
                outer.Approval.CreatedAt,outer.Approval.ExpiresAt,true,grant.SelectionProfile),
                additionalActive:()=>outer.CheckActive(grant,epoch.AddMilliseconds(monotonic()),monotonic()),
                requiredWindow:grant.Window);
        DiscoveryRequest ChildRequest(DiscoveryPolicy child) => new(3,child.Approval.Nonce,child.ApprovalSha256);
        foreach(var duplicateSecondLabel in new[]{false,true})
        {
            var outer=NewPolicy();var monotonic=0.0;var labelsSeen=new HashSet<string>(StringComparer.Ordinal);
            var published=new List<DiscoveryResult>();var totalRoots=0;var nativeChecks=0;
            for(var index=0;index<2;index++)
            {
                if(index==1)
                {
                    Check(!outer.Terminal && outer.NextEligibleMonotonicMilliseconds==2500,
                        "first500ms chunk establishes full2second cooldown");
                    monotonic=outer.NextEligibleMonotonicMilliseconds; // Never poll TryBegin early or retry a denial.
                }
                var grant=outer.TryBegin(Request(outer,index),identity,epoch.AddMilliseconds(monotonic),monotonic)!;
                Check(grant is not null && grant.RowStart==index*2 && grant.RowCount==2,"exact finite chunk admitted");
                using var fixture=new BatchTreeFixture();fixture.BuildGoalkeeperRows(grant.RowStart);
                if(index==1 && duplicateSecondLabel)
                    fixture.SetNodeText(BatchTreeFixture.GroupedLabelPath(2),"出击(倾向)");
                var child=Child(outer,grant,()=>monotonic);
                monotonic+=500; // Synthetic measured interval, not sleep or a live timing assertion.
                var result=TargetedDiscoveryCollector.Run(child,ChildRequest(child),
                    ()=>new BatchNativeBackend(context.GameHash,fixture.Bind),()=>{nativeChecks++;return identity;},
                    ()=>epoch.AddMilliseconds(monotonic),elapsedForTest:()=>500)!;
                Check(result.Status=="raw_diagnostics" && result.NativeOperations==1305 && result.Nodes==67 &&
                    result.TotalRoots==209 && result.PeakRoots==21 && result.ElapsedMilliseconds==500,
                    "actual child adapter completes exact bounded two-row group");
                Check(child.Terminal && fixture.LiveRoots==0 && fixture.RootCreates==fixture.RootFrees,
                    "each child cleanup completes before finite acknowledgment");
                totalRoots+=fixture.RootCreates;
                var valid=GroupedDiscoveryValidation.TryValidate(result,grant.SelectionProfile,out var labels);
                Check(valid,"each individual group has valid distinct observed labels");
                var freshLabels=labels.All(label=>!labelsSeen.Contains(label));
                var acknowledged=outer.Finish(grant,result.NativeOperations,result.ElapsedMilliseconds,valid && freshLabels,
                    epoch.AddMilliseconds(monotonic),monotonic);
                if(acknowledged)
                {
                    foreach(var label in labels) labelsSeen.Add(label);
                    published.Add(result); // Only after semantic checks, cleanup and outer acknowledgment.
                }
                Check(acknowledged==!(index==1 && duplicateSecondLabel),"cross-chunk duplicate labels deny the second output");
            }
            Check(outer.Terminal && outer.ChunksConsumed==2 && outer.TotalOperations==2610 && outer.TotalMilliseconds==1000 &&
                totalRoots==418 && nativeChecks==2750,"finite total includes both completed/failed semantic chunks and all native guard calls");
            Check(published.Count==(duplicateSecondLabel ? 1 : 2) && labelsSeen.Count==(duplicateSecondLabel ? 2 : 4),
                "no repeated labels or unacknowledged second result enter output");
            Check(outer.TryBegin(Request(outer,1),identity,epoch.AddSeconds(5),5000) is null,"terminal manifest never admits retry/third chunk");
        }
        {
            var outer=NewPolicy();var monotonic=0.0;
            var grant=outer.TryBegin(Request(outer,0),identity,epoch,monotonic)!;
            var child=Child(outer,grant,()=>monotonic);var factories=0;
            var replaced=identity with {WindowCandidates=new[]{identity.WindowCandidates![0] with {Hwnd=57}}};
            var result=TargetedDiscoveryCollector.Run(child,ChildRequest(child),()=>{factories++;throw new Exception("must not bind");},
                ()=>replaced,()=>epoch,elapsedForTest:()=>0);
            Check(result is null && child.Terminal && factories==0,"child cannot replace outer HWND between two independent fresh scans");
            Check(!outer.Finish(grant,0,0,false,epoch,0) && outer.Terminal,"failed child consumes and terminates outer manifest");
        }
        {
            var outer=NewPolicy();var monotonic=0.0;
            var grant=outer.TryBegin(Request(outer,0),identity,epoch,monotonic)!;
            using var fixture=new BatchTreeFixture();fixture.BuildGoalkeeperRows(0);
            var child=Child(outer,grant,()=>monotonic);
            var result=TargetedDiscoveryCollector.Run(child,ChildRequest(child),()=>new BatchNativeBackend(context.GameHash,fixture.Bind),
                ()=>{if(fixture.TextReads.Count>0) outer.Stop();return identity;},()=>epoch,elapsedForTest:()=>0)!;
            Check(result.Status=="terminal_failure" && result.Observations.Length==0 && fixture.TextReads.Count==1 && fixture.StringLengthReads==0,
                "outer revocation propagates through actual child guard before next text primitive");
            Check(fixture.LiveRoots==0 && fixture.RootCreates==fixture.RootFrees &&
                !outer.Finish(grant,result.NativeOperations,result.ElapsedMilliseconds,false,epoch,0) &&
                outer.TotalOperations==result.NativeOperations && outer.Terminal,"revoked work is cleaned and charged, never retried");
        }
        Console.WriteLine("PASS finite+child native composition fixtures;2610 units/418 roots/two500ms synthetic intervals, no game/time claim.");
    }
}
