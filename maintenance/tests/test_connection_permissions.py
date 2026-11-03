"""Free native permissions metadata verifies exact tools without executing them."""
from copy import deepcopy
from dataclasses import asdict
from aclad import connections
from aclad.models import GateError
from tests.support import StateTest


class ConnectionPermissionTests(StateTest):
    def setUp(self):
        super().setUp()
        self.assertTrue(hasattr(connections,'verify_connection_permissions'))
        self.tools=[dict(provider='data',connection_id='native-data',account_identity='seller@example.invalid',
            operation=op,tool_name='native.'+op,cost='free' if op=='connection.identity' else 'paid')
            for op in ('connection.identity','accounts.search','people.search')]
        self.caps=connections.discover(self.store,self.tools,True)
        self.cap=next(c for c in self.caps if c.operation=='connection.identity')
        self.metadata={'kind':'native_permissions','connection_id':self.cap.connection_id,
            'account_identity':'seller@example.invalid','permissions':[
                {'operation':c.operation,'tool_name':c.tool_name,'permission':'allowed'}
                for c in self.caps if c.operation!='connection.identity']}

    def probe(self,metadata=True):
        response={'connection_id':self.cap.connection_id,'status_code':200,
            'account_identity':'seller@example.invalid','evidence':'native-permission-response'}
        if metadata:response['permissions_metadata']=deepcopy(self.metadata)
        return connections.record_probe(self.store,self.cap,response)

    def verify(self, response=None, evidence_id='native-permission-response'):
        return connections.verify_connection_permissions(self.store,self.cap.connection_id,evidence_id,
            deepcopy(self.metadata) if response is None else response)

    def test_only_recorded_native_metadata_verifies_exact_operations_and_preserves_cost(self):
        self.probe()
        result=self.verify()
        self.assertEqual({c.operation for c in result},{'accounts.search','people.search'})
        self.assertTrue(all(c.verification=='verified' and c.permission=='allowed' and c.auth=='authenticated' for c in result))
        self.assertTrue(all(c.cost=='paid' for c in result))
        self.assertEqual(len(self.store.list('action')),0)

    def test_free_identity_without_permissions_metadata_cannot_promote_siblings(self):
        self.probe(metadata=False)
        with self.assertRaises(GateError):self.verify()
        search=next(row for row in self.store.list('connection') if row.data['capability']['operation']=='accounts.search')
        self.assertEqual(search.data['capability']['verification'],'declared')

    def test_no_read_proof_or_wrong_evidence_is_rejected(self):
        with self.assertRaises(GateError):self.verify()
        self.probe()
        with self.assertRaises(GateError):self.verify(evidence_id='not-the-native-evidence')

    def test_response_cannot_be_extended_beyond_recorded_metadata(self):
        self.probe()
        value=deepcopy(self.metadata)
        value['permissions'].append({'operation':'crm.write','tool_name':'native.write','permission':'allowed'})
        with self.assertRaises(GateError):self.verify(value)

    def test_wrong_tool_binding_and_denied_permissions_are_rejected_atomically(self):
        for field,value in [('tool_name','other.tool'),('permission','denied'),('operation','arbitrary.write')]:
            with self.subTest(field=field):
                bad=deepcopy(self.metadata);bad['permissions'][1][field]=value
                self.probe_with(bad)
                with self.assertRaises(GateError):self.verify(bad)
                self.assertEqual(next(r for r in self.store.list('connection') if r.data['capability']['operation']=='accounts.search').data['capability']['verification'],'declared')

    def probe_with(self,metadata):
        connections.record_probe(self.store,self.cap,{'connection_id':self.cap.connection_id,'status_code':200,
            'account_identity':'seller@example.invalid','evidence':'native-permission-response',
            'permissions_metadata':metadata})

    def test_identity_and_generation_change_invalidates_permission_metadata(self):
        self.probe()
        self.tools=[dict(t,account_identity='other@example.invalid') for t in self.tools]
        connections.discover(self.store,self.tools,True)
        with self.assertRaises(GateError):self.verify()

    def test_paid_identity_probe_cannot_grant_permissions(self):
        self.tools=[dict(t,cost='paid') for t in self.tools]
        caps=connections.discover(self.store,self.tools,True)
        self.cap=next(c for c in caps if c.operation=='connection.identity')
        self.probe()
        with self.assertRaises(GateError):self.verify()

    def test_native_metadata_must_match_exact_authenticated_identity(self):
        bad=deepcopy(self.metadata);bad['account_identity']='other@example.invalid'
        self.probe_with(bad)
        with self.assertRaises(GateError):self.verify(bad)
