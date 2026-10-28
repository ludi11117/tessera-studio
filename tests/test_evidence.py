import copy
import unittest

from ai.evidence import audit, literals, aligned
from ai.materials import initial
from ai.retrieval import prepare


class EvidenceTests(unittest.TestCase):
    def view(self,text,source_text='点击“导出 MD”，预算为30元。',facts=None):
        materials=initial([{'name':'操作规范.md','text':source_text}])
        task={'title':'使用说明','brief':'请写清实际步骤','facts':facts or {},'materials':materials,
              'blocks':[{'id':'section1','title':'操作步骤','variants':[{'id':'a','template':text}]}],
              'ai':{'sources':prepare(materials)}}
        return {'revision':7,'task':task,'state':{'combo':{'section1':'a'}}},materials

    def test_references_do_not_imply_supported_buttons_or_numbers(self):
        view,materials=self.view('点击“导出 PDF”，预算为50元。[M1#1]')
        result=audit(view,materials);claims=result['sections'][0]['paragraphs'][0]['literals']
        self.assertEqual(['not_found','not_found'],[c['status'] for c in claims])
        self.assertEqual('current',result['sections'][0]['sources'][0]['status'])
        self.assertEqual(2,result['summary']['review_items'])
        self.assertEqual('not_performed',result['semantic_fact_check'])

    def test_aligned_words_are_not_marked_as_semantically_verified(self):
        view,materials=self.view('点击“导出 MD”，预算为30元。[M1#1]')
        before=copy.deepcopy(view);result=audit(view,materials)
        self.assertEqual(0,result['summary']['review_items'])
        self.assertTrue(all(c['status']=='literal_present' for c in result['sections'][0]['paragraphs'][0]['literals']))
        self.assertEqual(before,view)
        self.assertNotIn('confidence',result)
        self.assertEqual('not_performed',result['semantic_fact_check'])

    def test_number_boundaries_lists_citations_code_and_whole_word_quotes(self):
        self.assertFalse(aligned({'kind':'number','text':'30元'},'130元'))
        self.assertFalse(aligned({'kind':'number','text':'5'},'5.5小时'))
        self.assertEqual(['30元'],[c['text'] for c in literals('1. 预算为30元 [M1#1] https://example.test/100')])
        self.assertEqual(['导出 PDF 2'],[c['text'] for c in literals('点击“导出 PDF 2”')])
        view,materials=self.view('```python\nx=999\n```\n点击“导出 MD”。[M1#1]')
        result=audit(view,materials)
        self.assertEqual(1,result['summary']['literal_count'])

    def test_fixed_conditions_goal_and_unicode_spacing_keep_explicit_provenance(self):
        view,materials=self.view('预算 {{budget}}，周期2周。',facts={'budget':'30元'})
        view['task']['brief']='周期2周的计划'
        claims=audit(view,materials)['sections'][0]['paragraphs'][0]['literals']
        self.assertEqual([['fact:budget'],['goal']],[c['matches'] for c in claims])
        self.assertTrue(aligned({'kind':'quoted_text','text':'导出 MD'},'点击导出　ＭＤ'))

    def test_no_cross_line_support_from_unrelated_source(self):
        view,materials=self.view('预算为30元。\n[M1#1]')
        result=audit(view,materials)
        self.assertEqual('no_reference',result['sections'][0]['paragraphs'][0]['literals'][0]['status'])

    def test_removed_unknown_and_tampered_sources_do_not_back_new_claims(self):
        view,materials=self.view('点击“导出 MD”。[M1#1] [M9#1]')
        removed=audit(view,[])['sections'][0]
        self.assertEqual(['removed','unknown'],[s['status'] for s in removed['sources']])
        self.assertEqual('no_reference',removed['paragraphs'][0]['literals'][0]['status'])
        view['task']['ai']['sources'][0]['text']='点击“导出 PDF”'
        tampered=audit(view,materials)['sections'][0]
        self.assertEqual('changed',tampered['sources'][0]['status'])
        self.assertEqual(64,len(tampered['text_sha256']))

    def test_hash_and_results_follow_revision_and_edit_without_labels(self):
        view,materials=self.view('点击“导出 MD”。[M1#1]')
        first=audit(view,materials)
        self.assertEqual(first,audit(copy.deepcopy(view),copy.deepcopy(materials)))
        view['revision']=8;view['task']['blocks'][0]['variants'][0]['template']='点击“导出 PDF”。[M1#1]'
        second=audit(view,materials)
        self.assertEqual(8,second['revision']);self.assertNotEqual(first['sections'][0]['text_sha256'],second['sections'][0]['text_sha256'])
        self.assertEqual(1,second['summary']['review_items'])


if __name__=='__main__':unittest.main()
