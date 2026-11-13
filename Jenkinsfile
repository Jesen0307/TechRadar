pipeline {
    agent any

    options {
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '30'))
    }

    environment {
        TOOLS_DIR = "${WORKSPACE}/.tools"
        DT_URL = "${params.DT_URL}"
        RUN_AGENT = "${params.RUN_AGENT}"
    }

    parameters {
        string(name: 'DT_URL', defaultValue: 'http://dependency-track-apiserver-1:8080')
        string(name: 'TAG', defaultValue: '')
        booleanParam(name: 'RUN_AGENT', defaultValue: true)
        booleanParam(name: 'ARCHIVE_RAW', defaultValue: false)
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
                sh 'rm -rf dump radar.json changes.md blips.previous.json'
            }
        }

        stage('Read previous blips') {
            steps {
                sh '''
                    if [ ! -f blips.json ]; then
                        echo '{"blips": [], "excluded": []}' > blips.json
                        echo "blips.json not found in the repository, starting empty (first run)"
                    fi
                    cp blips.json blips.previous.json
                    python3 -c "import json;d=json.load(open('blips.json'));print('Previous run: %d blips, %d excluded groups' % (len(d.get('blips', [])), len(d.get('excluded', []))))"
                '''
            }
        }

        stage('Prepare tools') {
            steps {
                timeout(time: 10, unit: 'MINUTES') {
                    sh '''
                        set -e
                        python3 --version
                        command -v curl >/dev/null 2>&1 || { echo "curl not found on this node"; exit 1; }
                        mkdir -p "$TOOLS_DIR/bin"
                        export PATH="$TOOLS_DIR/bin:$PATH"
                        if [ "$RUN_AGENT" = "true" ]; then
                            if ! command -v opencode >/dev/null 2>&1; then
                                echo "OpenCode not found, installing into $TOOLS_DIR/bin"
                                OPENCODE_INSTALL_DIR="$TOOLS_DIR/bin" curl -fsSL https://opencode.ai/install | bash
                            fi
                            opencode --version
                        fi
                    '''
                }
            }
        }

        stage('Fetch all components') {
            steps {
                script {
                    def args = ''
                    if (params.TAG?.trim()) {
                        if (!(params.TAG.trim() ==~ /[A-Za-z0-9_.-]+/)) { error 'Invalid TAG' }
                        args = "--tag ${params.TAG.trim()}"
                    }
                    env.DUMP_ARGS = args
                }
                withCredentials([string(credentialsId: 'dtrack-api-key', variable: 'DT_KEY')]) {
                    sh 'python3 dtrack_dump.py --url "$DT_URL" --out dump $DUMP_ARGS'
                }
            }
        }

        stage('Agent decides blips') {
            when { expression { params.RUN_AGENT } }
            steps {
                catchError(buildResult: 'SUCCESS', stageResult: 'FAILURE', message: 'AI agent did not finish') {
                    timeout(time: 30, unit: 'MINUTES') {
                        withEnv(["PATH+TOOLS=${env.TOOLS_DIR}/bin"]) {
                            aiAgent agent: openCode(),
                                    apiCredentialsId: 'OpenCode',
                                    failOnAgentError: false,
                                    model: 'opencode/deepseek-v4.1-flash-free',
                                    prompt: '''Read radar-playbook.md and follow it exactly.

Inputs:
- dump/components.json: all current components from Dependency-Track.
- blips.json in the repository root: the result of the previous radar run. It is the source of truth for the existing blips, with their names, quadrants, rings and components. If it has no blips, this is the first run.

Step 1: read blips.json first, then update blips.json in place so that it matches the current components.
Keep every existing blip as it is unless the data justifies a change, add blips for new technologies, and remove blips whose technology no longer appears.
Set isNew by comparing with the blips that were in blips.json when you started: blips that were already there are not new, blips you add are new. On the first run, when blips.json had no blips, set isNew to false for every blip.
Every id in dump/components.json must appear exactly once, in a blip or in excluded.
blips.json must contain only valid JSON, with no markdown, no code fences, and no text before or after it.

Step 2: after the file is written, your final reply must be a short human-readable summary built from the blips.json you just wrote.
Do not re-analyze anything and do not paste the JSON. Use exactly this layout:
## Radar Update
**Blips:** total, number new, number removed since the previous run, number of excluded components
**New:** names, or "none"
**Changed:** ring or quadrant changes, or "none"
**Low confidence:** names, or "none"
**Needs human attention:** one bullet per item

Do not modify any other file.''',
                                    yoloMode: true
                        }
                    }
                }
            }
        }

        stage('Validate blips') {
            steps {
                sh 'python3 build_radar.py --blips blips.json --components dump/components.json --previous blips.previous.json --check'
            }
        }

        stage('Build radar') {
            steps {
                sh 'python3 build_radar.py --blips blips.json --components dump/components.json --previous blips.previous.json --out radar.json --changes changes.md'
            }
        }
    }

    post {
        always {
            archiveArtifacts artifacts: 'radar.json, blips.json, blips.previous.json, changes.md, dump/components.json, dump/projects.json', allowEmptyArchive: true
            script {
                if (params.ARCHIVE_RAW) {
                    archiveArtifacts artifacts: 'dump/**', allowEmptyArchive: true
                }
            }
        }
    }
}
