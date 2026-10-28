import unittest
from ai.requirements import check


class RequirementTests(unittest.TestCase):
    def task(self,brief,category='writing',facts=None,titles=None):
        return {'brief':brief,'category':category,'facts':facts or {},'blocks':[{'title':t} for t in (titles or ['正文'])]}

    def test_explicit_total_length_excludes_reference_ids_and_whitespace(self):
        task=self.task('正文总计160–220个中文字符')
        result=check(task,'字'*170+' [M1#1]\n')
        self.assertEqual(170,result['length']['actual']);self.assertTrue(result['length']['within_range'])
        bad=check(task,'字'*92)
        self.assertFalse(bad['length']['within_range']);self.assertTrue(bad['warnings'])

    def test_ambiguous_ranges_are_not_collapsed_to_one_limit(self):
        self.assertNotIn('length',check(self.task('开头20–30字，正文160–220字'),'正文'))
        self.assertNotIn('length',check(self.task('准备20–30份资料'),'正文'))

    def test_seven_day_plan_does_not_pass_when_it_stops_at_four(self):
        task=self.task('七天Python学习计划','study',{'duration':'学习周期为7天'},['第1天','第2天','第3天','第4天'])
        result=check(task,'具体练习')
        self.assertEqual([5,6,7],result['days']['not_marked'])
        self.assertTrue(result['warnings'])

    def test_days_can_share_a_section_and_marks_are_conservative(self):
        task=self.task('七天学习计划','study',titles=['第1–3天','第4至7天'])
        self.assertEqual([],check(task,'练习安排')['days']['not_marked'])
        task['category']='analysis'
        self.assertNotIn('days',check(task,'分析七天数据'))


if __name__=='__main__':unittest.main()
