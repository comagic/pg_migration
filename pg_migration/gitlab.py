import asyncio
import os

import gitlab
import gitlab.const


class Gitlab:
    def __init__(self):
        url = 'https://' + os.environ['CI_SERVER_HOST']
        access_token = os.environ['ACCESS_TOKEN']
        self.gl = gitlab.Gitlab(url, access_token, api_version='4')
        self.gl.auth()
        self.user_id = os.environ['GITLAB_USER_ID']
        self.project_id = os.environ['CI_PROJECT_ID']

    def get_current_user_access_level(self):
        url = f"/projects/{self.project_id}/members/all/{self.user_id}"
        try:
            member = self.gl.http_get(url)
        except gitlab.exceptions.GitlabHttpError as e:
            print(f'get user access level error: {e}')
            return None
        return member['access_level']

    def check_permission(self):
        access_level = self.get_current_user_access_level()
        if access_level is None or access_level < gitlab.const.AccessLevel.MAINTAINER:
            print('ERROR: permission denied: only maintainer can make merge request for auto-deploy / auto-merge')
            exit(1)

    async def create_merge_request(self):
        self.check_permission()
        project = self.gl.projects.get(self.project_id)
        branch = os.environ['CI_COMMIT_REF_NAME']
        message = f'auto-merge: {branch}'
        mr = project.mergerequests.create({
            'source_branch': branch,
            'target_branch': 'master',
            'title': message,
            'remove_source_branch': True
        })
        await asyncio.sleep(4)
        message = f"Merge branch '{branch}' into 'master'"
        if 'auto-deploy' in os.environ['CI_COMMIT_MESSAGE']:
            message = 'auto-deploy: ' + message
        for i in range(5):
            try:
                mr.merge(
                    merge_commit_message=message,
                    merge_when_pipeline_succeeds=True
                )
                break
            except gitlab.exceptions.GitlabMRClosedError as e:
                if 'Method Not Allowed' in str(e):
                    print(f'Error: {e}')
                    if i == 4:
                        exit(1)
                    print(f'trying again...')
                    await asyncio.sleep(2)
