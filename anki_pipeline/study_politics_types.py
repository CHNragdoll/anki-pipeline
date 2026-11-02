"""Source-evidenced early Politics discrimination questions, without raw edits."""

def projected_question_type(category, year, question, original):
    """Classify only the nine audited questions with their printed section proof."""
    if (category == 'politics' and year in (2003, 2004, 2005)
            and str(question.get('number')) in {'31', '32', '33'}
            and original == 'free_response'):
        if '辨析' not in question.get('sectionTitle', ''):
            raise ValueError('audited politics discrimination question lacks printed section evidence')
        return 'discrimination'
    return original
